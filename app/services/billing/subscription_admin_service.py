"""BILL-01.3.2: manual, operator-authorized subscription operations.

No payment confirmation is implied by these operations. Operator-only; never expose
these functions through tenant-owner permissions or public checkout endpoints.
"""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.extensions import db
from app.models import Tenant
from app.models.billing import BillingPlan, BillingPlanPrice, TenantSubscription, SubscriptionAudit


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SubscriptionError(Exception):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


def _latest(tenant_id):
    return db.session.scalar(select(TenantSubscription).where(
        TenantSubscription.tenant_id == tenant_id
    ).order_by(TenantSubscription.created_at.desc(), TenantSubscription.id.desc()).limit(1))


def _price(price_id):
    price = db.session.get(BillingPlanPrice, price_id)
    plan = db.session.get(BillingPlan, price.plan_id) if price else None
    if not price or not price.active or not plan or not plan.active:
        raise SubscriptionError('invalid_plan_price', 422)
    return price


def _period(start, interval):
    # Calendar-aware month/year periods (no 30-day approximations).
    from calendar import monthrange
    months = 1 if interval == 'month' else 12
    year = start.year + (start.month - 1 + months) // 12
    month = (start.month - 1 + months) % 12 + 1
    day = min(start.day, monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def _audit(sub, action, old_status, actor_id):
    db.session.add(SubscriptionAudit(tenant_id=sub.tenant_id, subscription_id=sub.id,
                                     old_status=old_status, new_status=sub.status,
                                     action=action, actor_id=actor_id))


def assign_subscription(tenant_id, price_id, actor_id, *, status='trialing', trial_days=0):
    """Assign only a trial/incomplete record; never grant paid access directly."""
    if status not in ('trialing', 'incomplete') or isinstance(trial_days, bool) or not isinstance(trial_days, int) or not 0 <= trial_days <= 30:
        raise SubscriptionError('invalid_subscription_request', 422)
    try:
        tenant = db.session.get(Tenant, tenant_id)
        if tenant is None or tenant.status != 'active':
            raise SubscriptionError('tenant_not_found_or_inactive', 404)
        price = _price(price_id)
        previous = _latest(tenant_id)
        if previous and previous.status not in ('canceled', 'expired'):
            raise SubscriptionError('subscription_already_exists', 409)
        start = now_utc()
        sub = TenantSubscription(tenant_id=tenant_id, plan_price_id=price.id, status=status,
                                 current_period_start=start,
                                 current_period_end=_period(start, price.billing_interval),
                                 trial_ends_at=(start + timedelta(days=trial_days)) if status == 'trialing' else None)
        db.session.add(sub)
        db.session.flush()
        _audit(sub, 'assigned', None, actor_id)
        db.session.commit()
        return sub
    except Exception:
        db.session.rollback()
        raise


def change_plan(tenant_id, subscription_id, price_id, actor_id):
    """Manual change while preserving status and existing paid period.

    Not a payment, proration, or provider synchronization. Disabled for provider-linked records.
    """
    try:
        sub = db.session.scalar(select(TenantSubscription).where(
            TenantSubscription.id == subscription_id, TenantSubscription.tenant_id == tenant_id).with_for_update())
        if sub is None:
            raise SubscriptionError('subscription_not_found', 404)
        if _latest(tenant_id).id != sub.id or sub.status not in ('trialing', 'incomplete'):
            raise SubscriptionError('plan_change_not_allowed', 409)
        if sub.provider or sub.provider_subscription_id:
            raise SubscriptionError('provider_managed_subscription', 409)
        price = _price(price_id)
        if sub.plan_price_id == price.id:
            raise SubscriptionError('same_plan_price', 409)
        sub.plan_price_id = price.id
        if sub.current_period_start:
            sub.current_period_end = _period(sub.current_period_start, price.billing_interval)
        sub.updated_at = now_utc()
        _audit(sub, 'plan_changed', sub.status, actor_id)
        db.session.commit()
        return sub
    except Exception:
        db.session.rollback()
        raise


def cancel_subscription(tenant_id, subscription_id, actor_id):
    """Immediately cancel only manual trial/incomplete records."""
    try:
        sub = db.session.scalar(select(TenantSubscription).where(
            TenantSubscription.id == subscription_id, TenantSubscription.tenant_id == tenant_id).with_for_update())
        if sub is None:
            raise SubscriptionError('subscription_not_found', 404)
        if _latest(tenant_id).id != sub.id or sub.status not in ('trialing', 'incomplete'):
            raise SubscriptionError('cancellation_not_allowed', 409)
        if sub.provider or sub.provider_subscription_id:
            raise SubscriptionError('provider_managed_subscription', 409)
        old = sub.status
        sub.status = 'canceled'
        sub.canceled_at = now_utc()
        sub.ended_at = sub.canceled_at
        sub.updated_at = sub.canceled_at
        _audit(sub, 'canceled', old, actor_id)
        db.session.commit()
        return sub
    except Exception:
        db.session.rollback()
        raise
