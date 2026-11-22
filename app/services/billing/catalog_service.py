from sqlalchemy import select
from app.extensions import db
from app.models.billing import BillingPlan, BillingPlanPrice, BillingPlanEntitlement


def list_active_plans():
    plans = db.session.scalars(select(BillingPlan).where(BillingPlan.active.is_(True)).order_by(BillingPlan.id)).all()
    result = []
    for plan in plans:
        prices = db.session.scalars(select(BillingPlanPrice).where(BillingPlanPrice.plan_id == plan.id, BillingPlanPrice.active.is_(True)).order_by(BillingPlanPrice.id)).all()
        features = db.session.scalars(select(BillingPlanEntitlement).where(BillingPlanEntitlement.plan_id == plan.id).order_by(BillingPlanEntitlement.feature_code)).all()
        result.append({
            'id': plan.id, 'code': plan.code, 'name': plan.name,
            'description': plan.description,
            'prices': [{'id': p.id, 'currency': p.currency, 'billing_interval': p.billing_interval,
                        'amount': str(p.amount), 'version': p.version} for p in prices],
            'entitlements': [{'feature_code': e.feature_code, 'limit_value': e.limit_value} for e in features],
        })
    return result
