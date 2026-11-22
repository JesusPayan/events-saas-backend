"""BILL-03.7/03.8: focused renewal and known-resource reconciliation tests."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from app.extensions import db
from app.models.billing import BillingPlan, BillingPlanPrice, TenantSubscription
from app.models.mercadopago import MPCheckout, MPPayment
from app.services.billing.mercadopago_service import reconcile_payment
from app.services.billing.mercadopago_reconciliation import reconcile_known
from tests.test_identity import client, register


def _setup(client):
    tenant = register(client, 'renewal-mp@example.test', 'renewal-mp').json['tenant_id']
    with client.application.app_context():
        plan = BillingPlan(code='renewal-plan', name='Renewal plan', active=True)
        db.session.add(plan); db.session.flush()
        price = BillingPlanPrice(plan_id=plan.id, currency='MXN', billing_interval='month', amount=Decimal('299'), active=True)
        db.session.add(price); db.session.flush()
        checkout = MPCheckout(tenant_id=tenant, plan_price_id=price.id, payer_email='renewal-mp@example.test',
                              external_reference='renewal-checkout', provider_subscription_id='renewal-sub', status='authorized')
        db.session.add(checkout); db.session.commit()
    return tenant


def _payment(pid):
    return {'id': pid, 'preapproval_id': 'renewal-sub', 'transaction_amount': 299, 'currency_id': 'MXN', 'status': 'approved'}


def test_renewal_extends_existing_paid_through_date(client):
    _setup(client)
    with client.application.app_context():
        with patch('app.services.billing.mercadopago_service.api', side_effect=lambda *args, **kw: _payment(args[1].split('/')[-1])):
            assert reconcile_payment('payment-first')
            sub = db.session.query(TenantSubscription).one()
            initial_end = sub.current_period_end
            assert reconcile_payment('payment-second')
            db.session.refresh(sub)
            assert sub.current_period_start == initial_end
            assert sub.current_period_end > initial_end
            assert reconcile_payment('payment-second')
            assert db.session.query(MPPayment).count() == 2
            assert sub.current_period_start == initial_end


def test_known_resource_reconciliation_dry_run_has_no_api_calls(client):
    _setup(client)
    with client.application.app_context():
        with patch('app.services.billing.mercadopago_reconciliation.reconcile_preapproval') as provider:
            report = reconcile_known()
            assert report['mode'] == 'dry-run'
            assert report['checked'] == 1
            provider.assert_not_called()


def test_known_resource_reconciliation_apply(client):
    _setup(client)
    with client.application.app_context():
        with patch('app.services.billing.mercadopago_reconciliation.reconcile_preapproval', return_value=True) as provider:
            report = reconcile_known(apply=True)
            assert report['succeeded'] == 1
            provider.assert_called_once_with('renewal-sub')
