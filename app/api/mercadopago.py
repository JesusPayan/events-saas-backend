"""BILL-03: tenant checkout and signature-verified Mercado Pago notifications."""
from flask import Blueprint, jsonify, request, g
from app.security import tenant_permission
from app.services.billing.mercadopago_service import (create_checkout, reconcile_preapproval, reconcile_payment, signature_valid, BillingMPError)
from app.services.billing.mercadopago_client import MPError

bp = Blueprint('mercadopago_billing', __name__)

@bp.post('/billing/mercadopago/checkout')
@tenant_permission('tenant.read')
def checkout():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {'plan_price_id', 'payer_email'}:
        return jsonify(error='invalid_fields'), 422
    try:
        return jsonify(create_checkout(g.tenant_id, body['plan_price_id'], body['payer_email'])), 201
    except BillingMPError as exc:
        return jsonify(error=exc.code), exc.status
    except (MPError, KeyError):
        return jsonify(error='payment_provider_unavailable'), 503

@bp.post('/billing/mercadopago/webhook')
def webhook():
    resource_id = request.args.get('data.id') or request.args.get('id')
    kind = request.args.get('type') or request.args.get('topic')
    if not signature_valid(request.headers.get('x-signature'), request.headers.get('x-request-id'), resource_id):
        return jsonify(error='invalid_signature'), 401
    try:
        if kind == 'subscription_preapproval':
            reconcile_preapproval(resource_id)
        elif kind == 'subscription_authorized_payment':
            reconcile_payment(resource_id)
        else:
            return jsonify(accepted=True), 200
    except MPError:
        return jsonify(error='provider_temporarily_unavailable'), 503
    return jsonify(accepted=True), 200
