from sqlalchemy import select
from app.extensions import db
from app.models.billing import BillingPlan, BillingPlanPrice, BillingPlanEntitlement

FREE_PLAN_CODE = 'free'


def list_active_plans():
    plans = db.session.scalars(select(BillingPlan).where(BillingPlan.active.is_(True), BillingPlan.code != FREE_PLAN_CODE).order_by(BillingPlan.id)).all()
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


def public_catalog():
    """Catálogo para la landing pública: planes de pago activos y el plan Gratuito.

    Sin IDs internos de precio ni versiones: solo lo que un visitante necesita ver.
    Los importes salen de MySQL (fuente de verdad), nunca de valores fijos en el frontend.
    """
    def _features(plan_id):
        rows = db.session.scalars(select(BillingPlanEntitlement).where(
            BillingPlanEntitlement.plan_id == plan_id).order_by(BillingPlanEntitlement.feature_code)).all()
        return [{'feature_code': e.feature_code, 'limit_value': e.limit_value} for e in rows]

    plans = []
    for plan in list_active_plans():
        plans.append({
            'code': plan['code'], 'name': plan['name'], 'description': plan['description'],
            'prices': [{'billing_interval': p['billing_interval'], 'amount': p['amount'], 'currency': p['currency']}
                       for p in plan['prices']],
            'entitlements': plan['entitlements'],
        })
    free = db.session.scalar(select(BillingPlan).where(
        BillingPlan.code == FREE_PLAN_CODE, BillingPlan.active.is_(True)))
    free_tier = None if free is None else {
        'code': free.code, 'name': free.name, 'description': free.description, 'entitlements': _features(free.id),
    }
    return {'plans': plans, 'free_tier': free_tier}
