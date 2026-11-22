from sqlalchemy import select
from app.extensions import db
from app.models.billing import TenantSubscription, BillingPlanPrice, BillingPlan


def get_tenant_subscription(tenant_id):
    subscription = db.session.scalar(
        select(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id)
        .order_by(TenantSubscription.created_at.desc(), TenantSubscription.id.desc())
        .limit(1)
    )
    if subscription is None:
        return {'status': 'not_subscribed', 'subscription': None}
    price = db.session.get(BillingPlanPrice, subscription.plan_price_id)
    plan = db.session.get(BillingPlan, price.plan_id) if price else None
    return {
        'status': subscription.status,
        'subscription': {
            'id': subscription.id, 'plan_code': plan.code if plan else None,
            'plan_name': plan.name if plan else None,
            'plan_price_id': subscription.plan_price_id,
            'status': subscription.status,
            'current_period_start': subscription.current_period_start.isoformat() if subscription.current_period_start else None,
            'current_period_end': subscription.current_period_end.isoformat() if subscription.current_period_end else None,
            'trial_ends_at': subscription.trial_ends_at.isoformat() if subscription.trial_ends_at else None,
            'canceled_at': subscription.canceled_at.isoformat() if subscription.canceled_at else None,
        }
    }
