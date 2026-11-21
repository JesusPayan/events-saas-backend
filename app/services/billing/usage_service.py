from sqlalchemy import select, func
from app.extensions import db
from app.models.billing import BillingPlanPrice, BillingPlanEntitlement
from app.models.identity import Membership
from app.models.crm import Client
from app.models.event import Event
from app.services.billing.subscription_service import get_tenant_subscription

# Only mapped, audited counters are exposed. New feature codes require explicit mapping.
COUNTERS = {
    'members': lambda tenant_id: db.session.scalar(select(func.count()).select_from(Membership).where(Membership.tenant_id == tenant_id, Membership.status == 'active')),
    'clients': lambda tenant_id: db.session.scalar(select(func.count()).select_from(Client).where(Client.tenant_id == tenant_id, Client.status == 'active')),
    'events': lambda tenant_id: db.session.scalar(select(func.count()).select_from(Event).where(Event.tenant_id == tenant_id)),
}


def get_tenant_usage(tenant_id):
    state = get_tenant_subscription(tenant_id)
    sub = state['subscription']
    if sub is None:
        return {'status': 'not_subscribed', 'items': []}
    price = db.session.get(BillingPlanPrice, sub['plan_price_id'])
    if price is None:
        return {'status': state['status'], 'items': []}
    features = db.session.scalars(select(BillingPlanEntitlement).where(BillingPlanEntitlement.plan_id == price.plan_id).order_by(BillingPlanEntitlement.feature_code)).all()
    items = []
    for feature in features:
        counter = COUNTERS.get(feature.feature_code)
        used = int(counter(tenant_id) or 0) if counter else None
        items.append({'feature_code': feature.feature_code, 'limit_value': feature.limit_value,
                      'used': used, 'remaining': max(feature.limit_value - used, 0) if used is not None and feature.limit_value is not None else None})
    return {'status': state['status'], 'items': items}
