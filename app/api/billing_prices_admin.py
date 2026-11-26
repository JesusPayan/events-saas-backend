"""Versioned pricing and commercial overview for platform operators only.

Never a tenant permission: every route is guarded by ``operator_only``.
Price amounts are never edited in place. A change creates a new version and
deactivates the previous one, so contracted prices (referenced by
``tenant_subscriptions.plan_price_id`` and fixed in each Mercado Pago
preapproval) are never rewritten retroactively.
"""
import re
from decimal import Decimal, InvalidOperation
from flask import Blueprint, g, jsonify, request
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import Tenant
from app.models.billing import (
    BillingPlan, BillingPlanPrice, BillingPriceAudit, TenantSubscription, SubscriptionAudit,
)
from app.models.mercadopago import MPCheckout, MPPayment, MPReconciliationIssue
from app.api.billing_admin import any_operator, operator_only, plans_manager_only

bp = Blueprint('billing_prices_admin', __name__)

MAX_AMOUNT = Decimal('999999.99')


def _iso(value):
    return value.isoformat() if value else None


def _price(p):
    return {'id': p.id, 'amount': str(p.amount), 'currency': p.currency,
            'billing_interval': p.billing_interval, 'version': p.version,
            'active': bool(p.active), 'created_at': _iso(p.created_at)}


def _page_args(default_size=25):
    try:
        page = max(1, int(request.args.get('page', 1)))
        size = min(100, max(1, int(request.args.get('page_size', default_size))))
    except (TypeError, ValueError):
        page, size = 1, default_size
    return page, size


@bp.get('/billing/admin/prices')
@plans_manager_only
def list_prices():
    """Active prices per plan (``?history=1`` also returns inactive versions)."""
    include_history = request.args.get('history') in ('1', 'true')
    plans = db.session.scalars(select(BillingPlan).order_by(BillingPlan.id)).all()
    items = []
    for plan in plans:
        query = select(BillingPlanPrice).where(BillingPlanPrice.plan_id == plan.id)
        if not include_history:
            query = query.where(BillingPlanPrice.active.is_(True))
        prices = db.session.scalars(query.order_by(
            BillingPlanPrice.billing_interval, BillingPlanPrice.version.desc())).all()
        subscribers = db.session.scalar(
            select(func.count(TenantSubscription.id))
            .join(BillingPlanPrice, BillingPlanPrice.id == TenantSubscription.plan_price_id)
            .where(BillingPlanPrice.plan_id == plan.id,
                   TenantSubscription.status.in_(['active', 'trialing', 'past_due', 'paused']))) or 0
        items.append({'id': plan.id, 'code': plan.code, 'name': plan.name, 'active': bool(plan.active),
                      'active_subscriptions': int(subscribers),
                      'prices': [_price(p) for p in prices]})
    return jsonify(items=items), 200


@bp.get('/billing/admin/prices/audits')
@plans_manager_only
def price_audits():
    page, size = _page_args()
    query = select(BillingPriceAudit)
    plan_id = request.args.get('plan_id', type=int)
    if plan_id:
        query = query.where(BillingPriceAudit.plan_id == plan_id)
    total = db.session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.session.scalars(query.order_by(BillingPriceAudit.id.desc())
                              .offset((page - 1) * size).limit(size)).all()
    return jsonify(total=total, page=page, page_size=size, items=[{
        'id': a.id, 'plan_id': a.plan_id, 'plan_price_id': a.plan_price_id,
        'previous_price_id': a.previous_price_id, 'action': a.action,
        'old_amount': str(a.old_amount) if a.old_amount is not None else None,
        'new_amount': str(a.new_amount) if a.new_amount is not None else None,
        'actor_id': a.actor_id, 'created_at': _iso(a.created_at)} for a in rows]), 200


_AMOUNT_RE = re.compile(r'\d{1,6}(\.\d{1,2})?')


def _parse_amount(raw):
    if not isinstance(raw, str) or not _AMOUNT_RE.fullmatch(raw.strip()):
        return None
    try:
        amount = Decimal(raw.strip())
    except InvalidOperation:
        return None
    if (not amount.is_finite() or amount <= 0 or amount > MAX_AMOUNT
            or amount.as_tuple().exponent < -2):
        return None
    return amount.quantize(Decimal('0.01'))


@bp.post('/billing/admin/prices/<int:price_id>/reprice')
@plans_manager_only
def reprice(price_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {'amount'} or not isinstance(body['amount'], str):
        return jsonify(error='invalid_fields'), 422
    amount = _parse_amount(body['amount'])
    if amount is None:
        return jsonify(error='invalid_amount'), 422
    try:
        current = db.session.scalar(select(BillingPlanPrice).where(BillingPlanPrice.id == price_id).with_for_update())
        if current is None:
            db.session.rollback()
            return jsonify(error='price_not_found'), 404
        if not current.active:
            db.session.rollback()
            return jsonify(error='price_not_active'), 409
        if current.amount == amount:
            db.session.rollback()
            return jsonify(error='amount_unchanged'), 409
        version = db.session.scalar(select(func.max(BillingPlanPrice.version)).where(
            BillingPlanPrice.plan_id == current.plan_id,
            BillingPlanPrice.currency == current.currency,
            BillingPlanPrice.billing_interval == current.billing_interval)) or 0
        current.active = False
        next_price = BillingPlanPrice(plan_id=current.plan_id, currency=current.currency,
                                      billing_interval=current.billing_interval, amount=amount,
                                      version=version + 1, active=True)
        db.session.add(next_price)
        db.session.flush()
        db.session.add(BillingPriceAudit(plan_id=current.plan_id, plan_price_id=next_price.id,
                                         previous_price_id=current.id, action='reprice',
                                         old_amount=current.amount, new_amount=amount, actor_id=g.user.id))
        db.session.commit()
        return jsonify(price=_price(next_price)), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify(error='concurrent_price_update'), 409
    except Exception:
        db.session.rollback()
        raise


def _set_active(price_id, active):
    try:
        price = db.session.scalar(select(BillingPlanPrice).where(BillingPlanPrice.id == price_id).with_for_update())
        if price is None:
            db.session.rollback()
            return jsonify(error='price_not_found'), 404
        if bool(price.active) == active:
            db.session.rollback()
            return jsonify(error='state_unchanged'), 409
        previous = None
        if active:
            # Keep exactly one sellable price per plan/currency/interval.
            previous = db.session.scalar(select(BillingPlanPrice).where(
                BillingPlanPrice.plan_id == price.plan_id,
                BillingPlanPrice.currency == price.currency,
                BillingPlanPrice.billing_interval == price.billing_interval,
                BillingPlanPrice.active.is_(True)).with_for_update())
            if previous is not None:
                previous.active = False
        price.active = active
        db.session.add(BillingPriceAudit(
            plan_id=price.plan_id, plan_price_id=price.id,
            previous_price_id=previous.id if previous is not None else None,
            action='activate' if active else 'deactivate',
            old_amount=previous.amount if previous is not None else None,
            new_amount=price.amount, actor_id=g.user.id))
        db.session.commit()
        return jsonify(price=_price(price)), 200
    except Exception:
        db.session.rollback()
        raise


@bp.post('/billing/admin/prices/<int:price_id>/activate')
@plans_manager_only
def activate_price(price_id):
    return _set_active(price_id, True)


@bp.post('/billing/admin/prices/<int:price_id>/deactivate')
@plans_manager_only
def deactivate_price(price_id):
    return _set_active(price_id, False)


# ------------------------------------------------------------------
# Global commercial overview
# ------------------------------------------------------------------

@bp.get('/billing/admin/subscriptions')
@operator_only
def list_subscriptions():
    page, size = _page_args()
    status = request.args.get('status')
    query = (select(TenantSubscription, Tenant, BillingPlanPrice, BillingPlan)
             .join(Tenant, Tenant.id == TenantSubscription.tenant_id)
             .join(BillingPlanPrice, BillingPlanPrice.id == TenantSubscription.plan_price_id)
             .join(BillingPlan, BillingPlan.id == BillingPlanPrice.plan_id))
    if status:
        query = query.where(TenantSubscription.status == status)
    search = (request.args.get('q') or '').strip()
    if search:
        like = f"%{search[:80]}%"
        query = query.where((Tenant.name.like(like)) | (Tenant.slug.like(like)))
    total = db.session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.session.execute(query.order_by(TenantSubscription.id.desc())
                              .offset((page - 1) * size).limit(size)).all()
    return jsonify(total=total, page=page, page_size=size, items=[{
        'id': sub.id, 'tenant_id': tenant.id, 'tenant_name': tenant.name, 'tenant_slug': tenant.slug,
        'plan_code': plan.code, 'plan_name': plan.name, 'plan_price_id': price.id,
        'amount': str(price.amount), 'currency': price.currency, 'billing_interval': price.billing_interval,
        'price_version': price.version, 'status': sub.status, 'provider': sub.provider,
        'current_period_start': _iso(sub.current_period_start), 'current_period_end': _iso(sub.current_period_end),
        'canceled_at': _iso(sub.canceled_at), 'created_at': _iso(sub.created_at),
    } for sub, tenant, price, plan in rows]), 200


@bp.get('/billing/admin/tenants/<int:tenant_id>/payments')
@operator_only
def tenant_payments(tenant_id):
    provider_ids = select(MPCheckout.provider_subscription_id).where(
        MPCheckout.tenant_id == tenant_id, MPCheckout.provider_subscription_id.is_not(None))
    rows = db.session.scalars(select(MPPayment).where(MPPayment.provider_subscription_id.in_(provider_ids))
                              .order_by(MPPayment.id.desc()).limit(200)).all()
    return jsonify(items=[{'id': p.id, 'provider_payment_id': p.provider_payment_id, 'status': p.status,
                           'amount': str(p.amount), 'currency': p.currency, 'created_at': _iso(p.created_at)}
                          for p in rows]), 200


@bp.get('/billing/admin/tenants/<int:tenant_id>/audits')
@operator_only
def tenant_subscription_audits(tenant_id):
    rows = db.session.scalars(select(SubscriptionAudit).where(SubscriptionAudit.tenant_id == tenant_id)
                              .order_by(SubscriptionAudit.id.desc()).limit(200)).all()
    return jsonify(items=[{'id': a.id, 'subscription_id': a.subscription_id, 'action': a.action,
                           'old_status': a.old_status, 'new_status': a.new_status,
                           'actor_id': a.actor_id, 'created_at': _iso(a.created_at)} for a in rows]), 200


@bp.get('/billing/admin/reconciliation-issues')
@operator_only
def reconciliation_issues():
    include_resolved = request.args.get('resolved') in ('1', 'true')
    query = select(MPReconciliationIssue)
    if not include_resolved:
        query = query.where(MPReconciliationIssue.resolved_at.is_(None))
    rows = db.session.scalars(query.order_by(MPReconciliationIssue.last_seen_at.desc()).limit(200)).all()
    return jsonify(items=[{'id': i.id, 'resource_type': i.resource_type, 'resource_id': i.resource_id,
                           'reason': i.reason, 'attempts': i.attempts, 'first_seen_at': _iso(i.first_seen_at),
                           'last_seen_at': _iso(i.last_seen_at), 'resolved_at': _iso(i.resolved_at)}
                          for i in rows]), 200


@bp.get('/billing/admin/me')
@any_operator
def operator_me():
    """Lets the UI show the global panel only to configured operators."""
    return jsonify(operator=True, user_id=g.user.id), 200
