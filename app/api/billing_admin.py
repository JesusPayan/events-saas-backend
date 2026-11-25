"""BILL-01.3.3: platform-operator endpoints, fail closed by default.

Set BILLING_OPERATOR_USER_IDS on Flask config to explicit trusted user IDs.
This is NOT a tenant permission and must not be assigned to tenant owners.
"""
from functools import wraps
from flask import Blueprint, g, jsonify, request
from sqlalchemy import select
from app.security import authenticate
from app.extensions import db
from app.models.billing import TenantSubscription, SubscriptionAudit
from app.services.billing.subscription_admin_service import (
    SubscriptionError, assign_subscription, change_plan, cancel_subscription,
)

bp = Blueprint('billing_admin', __name__)


def _platform_guard(*permissions):
    """Permisos de plataforma (ROLES-01). Los IDs de BILLING_OPERATOR_USER_IDS
    conservan planes, suscripciones e incidencias por compatibilidad."""
    def outer(fn):
        @wraps(fn)
        @authenticate
        def wrapped(*args, **kwargs):
            if isinstance(g.user.id, bool):
                return jsonify(error='forbidden'), 403
            from app.services.platform_service import platform_permissions
            if not platform_permissions(g.user.id).intersection(permissions):
                return jsonify(error='forbidden'), 403
            return fn(*args, **kwargs)
        return wrapped
    return outer


# Suscripciones, pagos e incidencias: dueño y administradores de plataforma.
operator_only = _platform_guard('platform.billing.operate')
# Precios de planes: solo el dueño de plataforma (y operadores heredados).
plans_manager_only = _platform_guard('platform.plans.manage')
# Panel global: cualquiera de los dos.
any_operator = _platform_guard('platform.billing.operate', 'platform.plans.manage')


def _json():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise SubscriptionError('invalid_json', 400)
    return body


def _int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SubscriptionError('invalid_id', 422)
    return value


def _response(sub):
    return {'id': sub.id, 'tenant_id': sub.tenant_id, 'plan_price_id': sub.plan_price_id,
            'status': sub.status, 'current_period_start': sub.current_period_start.isoformat() if sub.current_period_start else None,
            'current_period_end': sub.current_period_end.isoformat() if sub.current_period_end else None}


@bp.post('/billing/admin/tenants/<int:tenant_id>/subscriptions')
@operator_only
def assign(tenant_id):
    try:
        body = _json()
        if set(body) - {'plan_price_id', 'status', 'trial_days'}:
            raise SubscriptionError('invalid_fields', 422)
        sub = assign_subscription(tenant_id, _int(body.get('plan_price_id')), g.user.id,
                                  status=body.get('status', 'trialing'), trial_days=body.get('trial_days', 0))
        return jsonify(subscription=_response(sub)), 201
    except SubscriptionError as exc:
        return jsonify(error=exc.code), exc.status


@bp.patch('/billing/admin/tenants/<int:tenant_id>/subscriptions/<int:subscription_id>/plan')
@operator_only
def plan_change(tenant_id, subscription_id):
    try:
        body = _json()
        if set(body) != {'plan_price_id'}:
            raise SubscriptionError('invalid_fields', 422)
        sub = change_plan(tenant_id, subscription_id, _int(body['plan_price_id']), g.user.id)
        return jsonify(subscription=_response(sub)), 200
    except SubscriptionError as exc:
        return jsonify(error=exc.code), exc.status


@bp.post('/billing/admin/tenants/<int:tenant_id>/subscriptions/<int:subscription_id>/cancel')
@operator_only
def cancel(tenant_id, subscription_id):
    try:
        sub = cancel_subscription(tenant_id, subscription_id, g.user.id)
        return jsonify(subscription=_response(sub)), 200
    except SubscriptionError as exc:
        return jsonify(error=exc.code), exc.status


@bp.get('/billing/admin/tenants/<int:tenant_id>/subscriptions/<int:subscription_id>/audits')
@operator_only
def audits(tenant_id, subscription_id):
    exists = db.session.scalar(select(TenantSubscription.id).where(
        TenantSubscription.id == subscription_id, TenantSubscription.tenant_id == tenant_id))
    if exists is None:
        return jsonify(error='subscription_not_found'), 404
    rows = db.session.scalars(select(SubscriptionAudit).where(
        SubscriptionAudit.tenant_id == tenant_id, SubscriptionAudit.subscription_id == subscription_id
    ).order_by(SubscriptionAudit.id)).all()
    return jsonify(items=[{'id': a.id, 'action': a.action, 'old_status': a.old_status,
                           'new_status': a.new_status, 'actor_id': a.actor_id} for a in rows]), 200
