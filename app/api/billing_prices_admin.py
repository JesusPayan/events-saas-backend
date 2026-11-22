"""Versioned pricing for platform operators only; never a tenant permission."""
from decimal import Decimal, InvalidOperation
from flask import Blueprint, jsonify, request
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models.billing import BillingPlan, BillingPlanPrice
from app.api.billing_admin import operator_only

bp = Blueprint('billing_prices_admin', __name__)

@bp.get('/billing/admin/prices')
@operator_only
def list_prices():
    plans = db.session.scalars(select(BillingPlan).order_by(BillingPlan.id)).all()
    items = []
    for plan in plans:
        prices = db.session.scalars(select(BillingPlanPrice).where(BillingPlanPrice.plan_id == plan.id, BillingPlanPrice.active.is_(True)).order_by(BillingPlanPrice.id)).all()
        items.append({'id': plan.id, 'code': plan.code, 'name': plan.name,
            'prices': [{'id': p.id, 'amount': str(p.amount), 'currency': p.currency, 'billing_interval': p.billing_interval, 'version': p.version} for p in prices]})
    return jsonify(items=items), 200

@bp.post('/billing/admin/prices/<int:price_id>/reprice')
@operator_only
def reprice(price_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {'amount'} or not isinstance(body['amount'], str):
        return jsonify(error='invalid_fields'), 422
    try:
        amount = Decimal(body['amount'])
    except InvalidOperation:
        return jsonify(error='invalid_amount'), 422
    if not amount.is_finite() or amount <= 0 or amount > Decimal('999999999999.99') or amount.as_tuple().exponent < -2:
        return jsonify(error='invalid_amount'), 422
    try:
        current = db.session.scalar(select(BillingPlanPrice).where(BillingPlanPrice.id == price_id).with_for_update())
        if current is None: return jsonify(error='price_not_found'), 404
        if not current.active: return jsonify(error='price_not_active'), 409
        if current.amount == amount: return jsonify(error='amount_unchanged'), 409
        version = db.session.scalar(select(func.max(BillingPlanPrice.version)).where(
            BillingPlanPrice.plan_id == current.plan_id,
            BillingPlanPrice.currency == current.currency,
            BillingPlanPrice.billing_interval == current.billing_interval)) or 0
        current.active = False
        next_price = BillingPlanPrice(plan_id=current.plan_id, currency=current.currency,
            billing_interval=current.billing_interval, amount=amount, version=version + 1, active=True)
        db.session.add(next_price)
        db.session.commit()
        return jsonify(price={'id': next_price.id, 'amount': str(next_price.amount),
            'currency': next_price.currency, 'billing_interval': next_price.billing_interval,
            'version': next_price.version}), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify(error='concurrent_price_update'), 409
    except Exception:
        db.session.rollback()
        raise
