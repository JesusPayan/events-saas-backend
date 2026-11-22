from app.services.billing.guards import require_entitlement
from flask import Blueprint, jsonify, g
from app.security import tenant_permission
from app.services.billing.catalog_service import list_active_plans
from app.services.billing.subscription_service import get_tenant_subscription
from app.services.billing.usage_service import get_tenant_usage

bp = Blueprint('billing', __name__)


@bp.get('/billing/plans')
@tenant_permission('tenant.read')
def plans():
    return jsonify(items=list_active_plans()), 200


@bp.get('/billing/subscription')
@tenant_permission('tenant.read')
def subscription():
    return jsonify(get_tenant_subscription(g.tenant_id)), 200


@bp.get('/billing/usage')
@tenant_permission('tenant.read')
def usage():
    return jsonify(get_tenant_usage(g.tenant_id)), 200


@bp.get('/billing/entitlements/<string:feature_code>')
@tenant_permission('tenant.read')
def entitlement_status(feature_code):
    from app.services.billing.entitlements_service import entitlement
    return jsonify(feature_code=feature_code, **entitlement(g.tenant_id, feature_code)), 200
