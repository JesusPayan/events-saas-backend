"""Provider-confirmed subscription lifecycle. Never trust browser success redirects."""
import hashlib
import hmac
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
from flask import current_app
from sqlalchemy import select
from app.extensions import db
from app.models.billing import BillingPlanPrice, BillingPlan, TenantSubscription, SubscriptionAudit, utc_now
from app.models.mercadopago import MPCheckout, MPWebhookEvent, MPPayment
from app.services.billing.mercadopago_client import api, MPError

class BillingMPError(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status

def signature_valid(header, request_id, resource_id):
    secret = current_app.config.get('MP_WEBHOOK_SECRET')
    if not secret or not header or not request_id or not resource_id:
        return False
    parts = dict(x.strip().split('=', 1) for x in header.split(',') if '=' in x)
    ts, digest = parts.get('ts'), parts.get('v1')
    if not ts or not digest or not ts.isdigit() or not re.fullmatch(r'[a-fA-F0-9]{64}', digest):
        return False
    if abs(int(datetime.now(timezone.utc).timestamp()) - int(ts) / 1000) > 300:
        return False
    manifest = f'id:{str(resource_id).lower()};request-id:{request_id};ts:{ts};'
    expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, digest.lower())

def create_checkout(tenant_id, price_id, payer_email):
    if not isinstance(price_id, int) or isinstance(price_id, bool) or price_id < 1:
        raise BillingMPError('invalid_plan_price', 422)
    if not isinstance(payer_email, str) or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', payer_email) or len(payer_email) > 254:
        raise BillingMPError('invalid_payer_email', 422)
    price = db.session.get(BillingPlanPrice, price_id)
    plan = db.session.get(BillingPlan, price.plan_id) if price else None
    if not price or not price.active or not plan or not plan.active or price.currency != 'MXN' or price.amount <= 0:
        raise BillingMPError('invalid_plan_price', 422)
    current = db.session.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id, TenantSubscription.status.in_(['active','trialing','past_due','paused'])).limit(1))
    if current:
        raise BillingMPError('subscription_already_exists', 409)
    pending = db.session.scalar(select(MPCheckout).where(MPCheckout.tenant_id == tenant_id, MPCheckout.status.in_(['pending','authorized'])).limit(1))
    if pending:
        raise BillingMPError('checkout_already_pending', 409)
    if not current_app.config.get('MP_BACK_URL', '').startswith('https://'):
        raise BillingMPError('invalid_return_url', 503)
    reference = 'evsaas-' + uuid.uuid4().hex
    checkout = MPCheckout(tenant_id=tenant_id, plan_price_id=price.id, payer_email=payer_email, external_reference=reference)
    db.session.add(checkout)
    db.session.commit()
    try:
        result = api('POST', '/preapproval', {
            'reason': f'Eventos SaaS - {plan.name}',
            'external_reference': reference,
            'payer_email': payer_email,
            'auto_recurring': {'frequency': 1, 'frequency_type': 'months' if price.billing_interval == 'month' else 'years',
                               'transaction_amount': float(price.amount), 'currency_id': 'MXN'},
            'back_url': current_app.config['MP_BACK_URL'],
            'status': 'pending',
        }, idempotency_key=reference)
        if not isinstance(result, dict) or not result.get('id') or not result.get('init_point'):
            raise MPError('invalid_provider_response')
        checkout.provider_subscription_id = str(result['id'])
        db.session.commit()
        return {'checkout_id': checkout.id, 'init_point': result['init_point'], 'status': 'pending'}
    except Exception:
        checkout.status = 'failed'
        db.session.commit()
        raise

def reconcile_preapproval(provider_id):
    """Status alone is NOT evidence of a settled payment."""
    remote = api('GET', '/preapproval/' + quote(str(provider_id), safe=''))
    checkout = db.session.scalar(select(MPCheckout).where(MPCheckout.provider_subscription_id == str(provider_id)).with_for_update())
    if not checkout or remote.get('external_reference') != checkout.external_reference or str(remote.get('id')) != str(provider_id):
        return False
    status = remote.get('status')
    if status in ('cancelled','canceled'):
        checkout.status = 'canceled'
        sub = db.session.scalar(select(TenantSubscription).where(TenantSubscription.provider == 'mercadopago', TenantSubscription.provider_subscription_id == str(provider_id)).with_for_update())
        if sub and sub.status != 'canceled':
            old = sub.status
            sub.status = 'canceled'
            sub.canceled_at = utc_now()
            sub.ended_at = sub.canceled_at
            db.session.add(SubscriptionAudit(tenant_id=sub.tenant_id, subscription_id=sub.id, old_status=old, new_status='canceled', action='mp_canceled'))
    elif status == 'authorized':
        checkout.status = 'authorized'  # not active until a verified payment
    db.session.commit()
    return True

def reconcile_payment(payment_id):
    """Verify payment via API; match amount/currency and provider subscription before granting access."""
    payment = api('GET', '/authorized_payments/' + quote(str(payment_id), safe=''))
    if not isinstance(payment, dict) or str(payment.get('id')) != str(payment_id):
        return False
    provider_id = str(payment.get('preapproval_id') or '')
    checkout = db.session.scalar(select(MPCheckout).where(MPCheckout.provider_subscription_id == provider_id).with_for_update())
    if not checkout:
        return False
    price = db.session.get(BillingPlanPrice, checkout.plan_price_id)
    try:
        amount = Decimal(str(payment.get('transaction_amount')))
    except (InvalidOperation, TypeError):
        return False
    if not price or payment.get('currency_id') != price.currency or amount != price.amount:
        return False
    status = payment.get('status')
    if status not in ('approved', 'processed'):
        return False
    if db.session.scalar(select(MPPayment.id).where(MPPayment.provider_payment_id == str(payment_id))):
        return True
    sub = db.session.scalar(select(TenantSubscription).where(TenantSubscription.provider == 'mercadopago', TenantSubscription.provider_subscription_id == provider_id).with_for_update())
    if sub is None:
        active = db.session.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id == checkout.tenant_id, TenantSubscription.status.in_(['active','trialing','past_due','paused'])).limit(1))
        if active:
            return False
        sub = TenantSubscription(tenant_id=checkout.tenant_id, plan_price_id=checkout.plan_price_id, status='incomplete', provider='mercadopago', provider_subscription_id=provider_id)
        db.session.add(sub)
        db.session.flush()
    if sub.status == 'canceled':
        return False
    old = sub.status
    from app.services.billing.subscription_admin_service import _period
    now = utc_now()
    sub.status = 'active'
    sub.current_period_start = now
    sub.current_period_end = _period(now, price.billing_interval)
    sub.updated_at = now
    checkout.status = 'active'
    db.session.add(MPPayment(provider_payment_id=str(payment_id), provider_subscription_id=provider_id, status=status, amount=amount, currency=price.currency))
    db.session.add(SubscriptionAudit(tenant_id=sub.tenant_id, subscription_id=sub.id, old_status=old, new_status='active', action='mp_payment_verified'))
    db.session.commit()
    return True
