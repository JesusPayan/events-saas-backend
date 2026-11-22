"""BILL-03.9.3: provider-state transition regression (SQLite unit fixture)."""
from unittest.mock import patch
from app.extensions import db
from app.models.mercadopago import MPPayment
from app.models.billing import TenantSubscription, SubscriptionAudit
from app.services.billing.mercadopago_service import reconcile_payment
from tests.test_billing_mp_production import _setup, _payment
from tests.test_identity import client


def test_refund_updates_ledger_without_extending_period(client):
    _setup(client)
    with client.application.app_context():
        response = _payment('refund-test-1')
        with patch('app.services.billing.mercadopago_service.api', return_value=response):
            assert reconcile_payment('refund-test-1')
        sub = db.session.query(TenantSubscription).one()
        paid_until = sub.current_period_end
        response = dict(response, status='refunded')
        with patch('app.services.billing.mercadopago_service.api', return_value=response):
            assert reconcile_payment('refund-test-1')
            assert reconcile_payment('refund-test-1')
        db.session.refresh(sub)
        assert sub.current_period_end == paid_until
        assert db.session.query(MPPayment).one().status == 'refunded'
        assert db.session.query(SubscriptionAudit).filter_by(action='mp_payment_reversed').count() == 1


def test_stale_approved_cannot_restore_refunded_payment(client):
    _setup(client)
    with client.application.app_context():
        response = _payment('refund-test-2')
        with patch('app.services.billing.mercadopago_service.api', return_value=response):
            assert reconcile_payment('refund-test-2')
        with patch('app.services.billing.mercadopago_service.api', return_value=dict(response, status='charged_back')):
            assert reconcile_payment('refund-test-2')
        with patch('app.services.billing.mercadopago_service.api', return_value=response):
            assert reconcile_payment('refund-test-2') is False
        assert db.session.query(MPPayment).one().status == 'charged_back'


def test_rejected_payment_does_not_activate(client):
    _setup(client)
    with client.application.app_context():
        with patch('app.services.billing.mercadopago_service.api', return_value=dict(_payment('rejected-1'), status='rejected')):
            assert reconcile_payment('rejected-1') is False
        assert db.session.query(TenantSubscription).count() == 0
        assert db.session.query(MPPayment).count() == 0
