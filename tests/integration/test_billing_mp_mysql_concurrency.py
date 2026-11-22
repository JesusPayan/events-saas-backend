"""BILL-03.9.1. Run ONLY on disposable MySQL crm_events_test.

Tests real InnoDB row locks using two independent Flask app contexts/connections.
Mercado Pago HTTP is mocked; this is not an external sandbox test.
"""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import select, func
from app.extensions import db
from app.models.billing import BillingPlan, BillingPlanPrice, TenantSubscription, SubscriptionAudit
from app.models.mercadopago import MPCheckout, MPPayment
from app.services.billing.mercadopago_service import reconcile_payment


def test_same_payment_concurrently_only_one_activation(flask_app, test_context):
    token = uuid4().hex[:18]
    tenant_id = test_context['tenant_id']
    provider_id = f'ci-sub-{token}'
    payment_id = f'ci-pay-{token}'
    plan_id = price_id = checkout_id = None

    with flask_app.app_context():
        try:
            plan = BillingPlan(code=f'ci-{token}', name='CI concurrency', active=True)
            db.session.add(plan)
            db.session.flush()
            plan_id = plan.id
            price = BillingPlanPrice(plan_id=plan.id, currency='MXN', billing_interval='month', amount=Decimal('299.00'), active=True)
            db.session.add(price)
            db.session.flush()
            price_id = price.id
            checkout = MPCheckout(tenant_id=tenant_id, plan_price_id=price.id,
                                  payer_email='mp-concurrency@example.test',
                                  external_reference=f'ci-ref-{token}',
                                  provider_subscription_id=provider_id, status='authorized')
            db.session.add(checkout)
            db.session.commit()
            checkout_id = checkout.id
        finally:
            db.session.remove()

    barrier = Barrier(2)

    def provider_api(method, path, *args, **kwargs):
        assert method == 'GET'
        assert path == f'/authorized_payments/{payment_id}'
        barrier.wait(timeout=15)  # both provider calls complete before DB lock
        return {'id': payment_id, 'preapproval_id': provider_id,
                'transaction_amount': 299, 'currency_id': 'MXN', 'status': 'approved'}

    def worker():
        with flask_app.app_context():
            try:
                return reconcile_payment(payment_id)
            finally:
                db.session.remove()

    try:
        with patch('app.services.billing.mercadopago_service.api', side_effect=provider_api):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(worker) for _ in range(2)]
                results = [f.result(timeout=30) for f in futures]
        assert results == [True, True]
        with flask_app.app_context():
            assert db.session.scalar(select(func.count()).select_from(MPPayment).where(MPPayment.provider_payment_id == payment_id)) == 1
            sub = db.session.scalar(select(TenantSubscription).where(
                TenantSubscription.provider == 'mercadopago',
                TenantSubscription.provider_subscription_id == provider_id))
            assert sub is not None and sub.status == 'active'
            assert sub.current_period_end > sub.current_period_start
            assert db.session.scalar(select(func.count()).select_from(SubscriptionAudit).where(
                SubscriptionAudit.subscription_id == sub.id,
                SubscriptionAudit.action == 'mp_payment_verified')) == 1
            db.session.rollback()
    finally:
        # Test-only cleanup, in FK order. Never point this fixture at production.
        with flask_app.app_context():
            try:
                sub = db.session.scalar(select(TenantSubscription).where(
                    TenantSubscription.provider == 'mercadopago',
                    TenantSubscription.provider_subscription_id == provider_id))
                if sub:
                    db.session.query(SubscriptionAudit).filter(SubscriptionAudit.subscription_id == sub.id).delete(synchronize_session=False)
                    db.session.delete(sub)
                    db.session.flush()
                db.session.query(MPPayment).filter(MPPayment.provider_payment_id == payment_id).delete(synchronize_session=False)
                if checkout_id:
                    checkout = db.session.get(MPCheckout, checkout_id)
                    if checkout:
                        db.session.delete(checkout)
                db.session.flush()
                if price_id:
                    price = db.session.get(BillingPlanPrice, price_id)
                    if price:
                        db.session.delete(price)
                db.session.flush()
                if plan_id:
                    plan = db.session.get(BillingPlan, plan_id)
                    if plan:
                        db.session.delete(plan)
                db.session.commit()
            except Exception:
                db.session.rollback()
                raise
            finally:
                db.session.remove()
