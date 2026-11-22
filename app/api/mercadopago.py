"""Mercado Pago: checkout and verified, durably deduplicated notifications."""
import re
import hashlib
from flask import Blueprint, jsonify, request, g
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models.mercadopago import MPWebhookEvent, MPReconciliationIssue
from app.models.billing import utc_now
from app.security import tenant_permission
from app.services.billing.mercadopago_service import (
    create_checkout, reconcile_preapproval, reconcile_payment,
    signature_valid, BillingMPError, latest_checkout, cancel_tenant_subscription,
)
from app.services.billing.mercadopago_client import MPError

bp = Blueprint('mercadopago_billing', __name__)
_KINDS = {'subscription_preapproval', 'subscription_authorized_payment'}
_RESOURCE_ID = re.compile(r'^[A-Za-z0-9_-]{1,100}$')

@bp.post('/billing/mercadopago/checkout')
@tenant_permission('billing.manage')
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

@bp.get('/billing/mercadopago/checkout/latest')
@tenant_permission('tenant.read')
def checkout_latest():
    return jsonify(latest_checkout(g.tenant_id)), 200


@bp.post('/billing/mercadopago/cancel')
@tenant_permission('billing.manage')
def cancel():
    try:
        return jsonify(cancel_tenant_subscription(g.tenant_id, g.user.id)), 200
    except BillingMPError as exc:
        return jsonify(error=exc.code), exc.status
    except MPError:
        db.session.rollback()
        return jsonify(error='payment_provider_unavailable'), 503


@bp.post('/billing/mercadopago/webhook')
def webhook():
    resource_id = request.args.get('data.id') or request.args.get('id')
    kind = request.args.get('type') or request.args.get('topic')
    if not resource_id or not _RESOURCE_ID.fullmatch(resource_id):
        return jsonify(error='invalid_resource_id'), 400
    if not signature_valid(request.headers.get('x-signature'), request.headers.get('x-request-id'), resource_id):
        return jsonify(error='invalid_signature'), 401
    if kind not in _KINDS:
        return jsonify(accepted=True, ignored=True), 200
    handler = reconcile_preapproval if kind == 'subscription_preapproval' else reconcile_payment
    # A new delivery ID for the same resource must be reconciled again:
    # provider statuses may change after the initial notification.
    request_id = request.headers.get('x-request-id', '')
    event_key = hashlib.sha256(
        f'{kind}:{resource_id}:{request_id}'.encode('utf-8')
    ).hexdigest()
    if db.session.scalar(select(MPWebhookEvent.id).where(MPWebhookEvent.event_key == event_key)):
        return jsonify(accepted=True, duplicate=True), 200
    try:
        reconciled = handler(resource_id)
        if not reconciled:
            # Unknown/unmatched resource: do not mark as processed, so it can be retried.
            _record_issue(kind, resource_id, 'not_reconciled')
            return jsonify(error='resource_not_reconciled'), 503
        db.session.add(MPWebhookEvent(event_key=event_key, resource_type=kind, resource_id=resource_id))
        _resolve_issue(kind, resource_id)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        # Concurrent delivery of the same event; unique index enforces deduplication.
        if db.session.scalar(select(MPWebhookEvent.id).where(MPWebhookEvent.event_key == event_key)):
            return jsonify(accepted=True, duplicate=True), 200
        return jsonify(error='webhook_persistence_failed'), 503
    except MPError:
        db.session.rollback()
        _record_issue(kind, resource_id, 'provider_unavailable')
        return jsonify(error='provider_temporarily_unavailable'), 503
    except Exception:
        db.session.rollback()
        raise
    return jsonify(accepted=True), 200


def _record_issue(kind, resource_id, reason):
    """Best effort: never let bookkeeping break the webhook response."""
    try:
        db.session.rollback()
        issue = db.session.scalar(select(MPReconciliationIssue).where(
            MPReconciliationIssue.resource_type == kind,
            MPReconciliationIssue.resource_id == resource_id).with_for_update())
        now = utc_now()
        if issue is None:
            db.session.add(MPReconciliationIssue(resource_type=kind, resource_id=resource_id, reason=reason,
                                                 attempts=1, first_seen_at=now, last_seen_at=now))
        else:
            issue.attempts += 1
            issue.reason = reason
            issue.last_seen_at = now
            issue.resolved_at = None
        db.session.commit()
    except Exception:
        db.session.rollback()


def _resolve_issue(kind, resource_id):
    issue = db.session.scalar(select(MPReconciliationIssue).where(
        MPReconciliationIssue.resource_type == kind,
        MPReconciliationIssue.resource_id == resource_id,
        MPReconciliationIssue.resolved_at.is_(None)))
    if issue is not None:
        issue.resolved_at = utc_now()
