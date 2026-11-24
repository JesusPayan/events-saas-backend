"""BILL-02.2/02.3: server-side enforcement after tenant_permission."""
from functools import wraps
from flask import current_app, g, jsonify
from sqlalchemy import select
from app.extensions import db
from app.models import Tenant
from app.services.billing.entitlements_service import entitlement


def require_entitlement(feature_code, *, serialize_creates=False):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not current_app.config.get('BILLING_ENFORCE_ENTITLEMENTS', False):
                return fn(*args, **kwargs)
            # Lock the tenant row until the create commits, serializing concurrent
            # creates for a tenant on MySQL/InnoDB. Never commit before the handler.
            if serialize_creates:
                db.session.scalar(select(Tenant).where(Tenant.id == g.tenant_id).with_for_update())
            result = entitlement(g.tenant_id, feature_code)
            if not result['allowed']:
                db.session.rollback()  # releases any lock on rejection
                return jsonify(error='billing_entitlement_denied', feature_code=feature_code,
                               reason=result['reason'], limit=result['limit'], used=result['used'],
                               tier=result.get('tier')), 403
            return fn(*args, **kwargs)
        return wrapped
    return decorate
