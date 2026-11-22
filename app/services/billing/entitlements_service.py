"""BILL-02.1: tenant-scoped, fail-closed entitlement evaluation."""
from datetime import datetime, timezone
from sqlalchemy import select
from app.extensions import db
from app.models.billing import TenantSubscription, BillingPlanPrice, BillingPlanEntitlement
from app.services.billing.usage_service import COUNTERS

VALID_STATES = frozenset(('active', 'trialing'))


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def entitlement(tenant_id, feature_code, *, at=None):
    """Return explicit decision. Missing or invalid subscriptions never grant access."""
    now = at or _now()
    sub = db.session.scalar(select(TenantSubscription).where(
        TenantSubscription.tenant_id == tenant_id
    ).order_by(TenantSubscription.created_at.desc(), TenantSubscription.id.desc()).limit(1))
    if sub is None:
        return {'allowed': False, 'reason': 'not_subscribed', 'limit': 0, 'used': None}
    if sub.status not in VALID_STATES:
        return {'allowed': False, 'reason': 'subscription_inactive', 'limit': 0, 'used': None}
    if sub.current_period_start and now < sub.current_period_start:
        return {'allowed': False, 'reason': 'period_not_started', 'limit': 0, 'used': None}
    if sub.current_period_end is None or now >= sub.current_period_end:
        return {'allowed': False, 'reason': 'period_expired', 'limit': 0, 'used': None}
    if sub.status == 'trialing' and (sub.trial_ends_at is None or now >= sub.trial_ends_at):
        return {'allowed': False, 'reason': 'trial_expired', 'limit': 0, 'used': None}
    price = db.session.get(BillingPlanPrice, sub.plan_price_id)
    if price is None:
        return {'allowed': False, 'reason': 'invalid_plan', 'limit': 0, 'used': None}
    item = db.session.scalar(select(BillingPlanEntitlement).where(
        BillingPlanEntitlement.plan_id == price.plan_id,
        BillingPlanEntitlement.feature_code == feature_code))
    if item is None or item.limit_value == 0:
        return {'allowed': False, 'reason': 'feature_disabled', 'limit': 0, 'used': None}
    counter = COUNTERS.get(feature_code)
    used = int(counter(tenant_id) or 0) if counter else None
    if item.limit_value is not None and used is not None and used >= item.limit_value:
        return {'allowed': False, 'reason': 'limit_reached', 'limit': item.limit_value, 'used': used}
    return {'allowed': True, 'reason': 'allowed', 'limit': item.limit_value, 'used': used}
