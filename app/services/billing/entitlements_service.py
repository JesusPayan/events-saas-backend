"""BILL-02.1: tenant-scoped, fail-closed entitlement evaluation.

Política comercial v1.0:
- Suscripción vigente (active/trialing, o canceled dentro del periodo pagado): límites del plan contratado.
- Sin suscripción vigente: límites del nivel gratuito (plan ``free`` en MySQL).
- Si el nivel gratuito no está sembrado, se niega (fail-closed).
"""
from datetime import datetime, timezone
from sqlalchemy import select
from app.extensions import db
from app.models.billing import TenantSubscription, BillingPlan, BillingPlanPrice, BillingPlanEntitlement
from app.services.billing.usage_service import COUNTERS

VALID_STATES = frozenset(('active', 'trialing'))
FREE_PLAN_CODE = 'free'


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _deny(reason):
    return {'allowed': False, 'reason': reason, 'limit': 0, 'used': None}


def subscription_access(tenant_id, *, at=None):
    """Return (plan_id, None) when a paid subscription grants access, else (None, reason)."""
    now = at or _now()
    sub = db.session.scalar(select(TenantSubscription).where(
        TenantSubscription.tenant_id == tenant_id
    ).order_by(TenantSubscription.created_at.desc(), TenantSubscription.id.desc()).limit(1))
    if sub is None:
        return None, 'not_subscribed'
    if sub.status == 'canceled':
        # Cancelada: conserva el acceso hasta el final del periodo pagado.
        if sub.current_period_end is None or now >= sub.current_period_end:
            return None, 'subscription_inactive'
    elif sub.status not in VALID_STATES:
        return None, 'subscription_inactive'
    if sub.current_period_start and now < sub.current_period_start:
        return None, 'period_not_started'
    if sub.current_period_end is None or now >= sub.current_period_end:
        return None, 'period_expired'
    if sub.status == 'trialing' and (sub.trial_ends_at is None or now >= sub.trial_ends_at):
        return None, 'trial_expired'
    price = db.session.get(BillingPlanPrice, sub.plan_price_id)
    if price is None:
        return None, 'invalid_plan'
    return price.plan_id, None


def free_plan_id():
    return db.session.scalar(select(BillingPlan.id).where(
        BillingPlan.code == FREE_PLAN_CODE, BillingPlan.active.is_(True)))


def effective_plan(tenant_id, *, at=None):
    """Return (plan_id, tier, reason): tier is 'paid', 'free' or None (no access)."""
    plan_id, reason = subscription_access(tenant_id, at=at)
    if plan_id is not None:
        return plan_id, 'paid', None
    free_id = free_plan_id()
    if free_id is not None:
        return free_id, 'free', reason
    return None, None, reason


def entitlement(tenant_id, feature_code, *, at=None):
    """Return explicit decision. Missing or invalid subscriptions never grant paid access."""
    plan_id, tier, reason = effective_plan(tenant_id, at=at)
    if plan_id is None:
        return _deny(reason)
    item = db.session.scalar(select(BillingPlanEntitlement).where(
        BillingPlanEntitlement.plan_id == plan_id,
        BillingPlanEntitlement.feature_code == feature_code))
    if item is None or item.limit_value == 0:
        return dict(_deny('feature_disabled'), tier=tier)
    counter = COUNTERS.get(feature_code)
    used = int(counter(tenant_id) or 0) if counter else None
    if item.limit_value is not None and used is not None and used >= item.limit_value:
        return {'allowed': False, 'reason': 'limit_reached', 'limit': item.limit_value, 'used': used, 'tier': tier}
    return {'allowed': True, 'reason': 'allowed', 'limit': item.limit_value, 'used': used, 'tier': tier}
