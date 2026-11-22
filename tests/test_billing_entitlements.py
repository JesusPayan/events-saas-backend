"""BILL-02.4: tenant isolation, expiry, feature flags and creation limits."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import select
from app.extensions import db
from app.models.billing import BillingPlan, BillingPlanPrice, BillingPlanEntitlement, TenantSubscription
from app.services.billing.entitlements_service import entitlement
from tests.test_identity import client
from tests.test_billing_api import tenants


def provision(tenant_id, code, *, status='active', limit=1, trial_days=None):
    plan = BillingPlan(code=code, name=code)
    db.session.add(plan)
    db.session.flush()
    price = BillingPlanPrice(plan_id=plan.id, currency='MXN', billing_interval='month', amount=Decimal('299.00'))
    db.session.add(price)
    db.session.flush()
    db.session.add(BillingPlanEntitlement(plan_id=plan.id, feature_code='clients', limit_value=limit))
    db.session.add(BillingPlanEntitlement(plan_id=plan.id, feature_code='advanced_reports', limit_value=0))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sub = TenantSubscription(tenant_id=tenant_id, plan_price_id=price.id, status=status,
                             current_period_start=now-timedelta(days=1), current_period_end=now+timedelta(days=20),
                             trial_ends_at=(now+timedelta(days=trial_days)) if trial_days is not None else None)
    db.session.add(sub)
    db.session.commit()
    return sub


def test_no_subscription_denied(tenants):
    with tenants['client'].application.app_context():
        assert entitlement(tenants['a'], 'clients')['reason'] == 'not_subscribed'


def test_tenant_isolation_and_limits(tenants):
    with tenants['client'].application.app_context():
        provision(tenants['a'], 'basic-test', limit=1)
        provision(tenants['b'], 'pro-test', limit=None)
        assert entitlement(tenants['a'], 'clients')['limit'] == 1
        assert entitlement(tenants['b'], 'clients')['limit'] is None
        assert entitlement(tenants['a'], 'advanced_reports')['reason'] == 'feature_disabled'
        assert entitlement(tenants['b'], 'unknown')['reason'] == 'feature_disabled'


def test_expired_and_inactive(tenants):
    with tenants['client'].application.app_context():
        sub = provision(tenants['a'], 'expired-test')
        sub.current_period_end = datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=1)
        db.session.commit()
        assert entitlement(tenants['a'], 'clients')['reason'] == 'period_expired'
        sub.status = 'past_due'
        db.session.commit()
        assert entitlement(tenants['a'], 'clients')['reason'] == 'subscription_inactive'


def test_trial_without_end_is_denied(tenants):
    with tenants['client'].application.app_context():
        provision(tenants['a'], 'trial-test', status='trialing')
        assert entitlement(tenants['a'], 'clients')['reason'] == 'trial_expired'


def test_api_read_is_tenant_scoped(tenants):
    with tenants['client'].application.app_context():
        provision(tenants['a'], 'a-test', limit=1)
    a = tenants['client'].get('/api/v1/billing/entitlements/clients', headers=tenants['ha'])
    b = tenants['client'].get('/api/v1/billing/entitlements/clients', headers=tenants['hb'])
    assert a.status_code == b.status_code == 200
    assert a.json['allowed'] is True
    assert b.json['reason'] == 'not_subscribed'


def test_enforcement_flag_blocks_unsubscribed_creates(tenants):
    c = tenants['client']
    c.application.config['BILLING_ENFORCE_ENTITLEMENTS'] = True
    try:
        r = c.post('/api/v1/clients', json={}, headers=tenants['ha'])
        assert r.status_code == 403
        assert r.json['reason'] == 'not_subscribed'
    finally:
        c.application.config['BILLING_ENFORCE_ENTITLEMENTS'] = False


def test_enforcement_disabled_keeps_validation(tenants):
    r = tenants['client'].post('/api/v1/clients', json={}, headers=tenants['ha'])
    assert r.status_code == 400
