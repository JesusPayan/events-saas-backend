"""BILL-04 v1.0 hardening regression tests (SQLite in-memory fixture).

Covers: charge-result verification of authorized_payments, rejected renewals,
tenant cancellation confirmed by the provider, billing.manage permission,
operator price versioning/audit, global subscription overview, webhook
reconciliation issues, production configuration and security headers.
"""
import hashlib
import hmac
import time
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app import _validate_production_config, create_app
from app.extensions import db
from app.models.billing import (
    BillingPlan, BillingPlanPrice, BillingPriceAudit, SubscriptionAudit, TenantSubscription,
)
from app.models.identity import Membership, Permission, Role, RolePermission, User
from app.models.mercadopago import MPCheckout, MPPayment, MPReconciliationIssue
from app.services.billing.mercadopago_service import effective_payment_status, reconcile_payment
from tests.test_identity import client, register, token  # noqa: F401

API = 'app.services.billing.mercadopago_service.api'


def _owner(client, email, slug):
    r = register(client, email, slug)
    assert r.status_code == 201, r.json
    tenant = r.json['tenant_id']
    headers = {'Authorization': 'Bearer ' + token(client, email), 'X-Tenant-ID': str(tenant)}
    return tenant, headers


def _price(amount='299.00', interval='month', code='v1-basic'):
    plan = db.session.scalar(select(BillingPlan).where(BillingPlan.code == code))
    if plan is None:
        plan = BillingPlan(code=code, name='Básico', active=True)
        db.session.add(plan)
        db.session.flush()
    price = BillingPlanPrice(plan_id=plan.id, currency='MXN', billing_interval=interval,
                             amount=Decimal(amount), version=1, active=True)
    db.session.add(price)
    db.session.commit()
    return price


def _checkout(tenant, price, provider_id='mp-sub-v1', status='authorized'):
    db.session.add(MPCheckout(tenant_id=tenant, plan_price_id=price.id, payer_email='x@example.test',
                              external_reference='ref-' + provider_id, provider_subscription_id=provider_id,
                              status=status))
    db.session.commit()


def _invoice(pid, provider_id='mp-sub-v1', top='processed', charge='approved', amount=299):
    data = {'id': pid, 'preapproval_id': provider_id, 'transaction_amount': amount,
            'currency_id': 'MXN', 'status': top}
    if charge is not None:
        data['payment'] = {'id': 9000, 'status': charge, 'status_detail': 'x'}
    return data


# ------------------------------------------------------------------
# Payment verification
# ------------------------------------------------------------------

def test_effective_status_requires_charge_result():
    assert effective_payment_status({'status': 'processed'}) == 'unverified'
    assert effective_payment_status({'status': 'scheduled'}) == 'unverified'
    assert effective_payment_status({'status': 'recycling'}) == 'unverified'
    assert effective_payment_status({'status': 'processed', 'payment': {'status': 'rejected'}}) == 'rejected'
    assert effective_payment_status({'status': 'processed', 'payment': {'status': 'approved'}}) == 'approved'
    assert effective_payment_status({'status': 'approved'}) == 'approved'


def test_processed_invoice_with_rejected_charge_never_activates(client):
    tenant, _ = _owner(client, 'v1-rej@example.test', 'v1-rej')
    with client.application.app_context():
        _checkout(tenant, _price())
        with patch(API, return_value=_invoice('inv-1', charge='rejected')):
            assert reconcile_payment('inv-1') is False
        with patch(API, return_value=_invoice('inv-2', charge=None)):
            assert reconcile_payment('inv-2') is False
        assert db.session.query(TenantSubscription).count() == 0
        assert db.session.query(MPPayment).count() == 0


def test_processed_invoice_with_approved_charge_activates(client):
    tenant, _ = _owner(client, 'v1-ok@example.test', 'v1-ok')
    with client.application.app_context():
        _checkout(tenant, _price())
        with patch(API, return_value=_invoice('inv-ok')):
            assert reconcile_payment('inv-ok') is True
        sub = db.session.query(TenantSubscription).one()
        assert sub.status == 'active' and sub.tenant_id == tenant


def test_amount_mismatch_never_activates(client):
    tenant, _ = _owner(client, 'v1-amt@example.test', 'v1-amt')
    with client.application.app_context():
        _checkout(tenant, _price())
        with patch(API, return_value=_invoice('inv-amt', amount=1)):
            assert reconcile_payment('inv-amt') is False
        assert db.session.query(TenantSubscription).count() == 0


def test_rejected_renewal_is_audited_and_keeps_paid_period(client):
    tenant, _ = _owner(client, 'v1-renew@example.test', 'v1-renew')
    with client.application.app_context():
        _checkout(tenant, _price())
        with patch(API, return_value=_invoice('inv-a')):
            assert reconcile_payment('inv-a') is True
        sub = db.session.query(TenantSubscription).one()
        paid_until = sub.current_period_end
        with patch(API, return_value=_invoice('inv-b', charge='rejected')):
            assert reconcile_payment('inv-b') is True  # handled: stop provider retries
        db.session.refresh(sub)
        assert sub.status == 'active'  # period not over yet
        assert sub.current_period_end == paid_until
        assert db.session.query(SubscriptionAudit).filter_by(action='mp_payment_rejected').count() == 1


# ------------------------------------------------------------------
# Tenant cancellation & checkout permissions
# ------------------------------------------------------------------

def _active_subscription(client, tenant):
    _checkout(tenant, _price())
    with patch(API, return_value=_invoice('inv-c')):
        assert reconcile_payment('inv-c') is True


def test_cancel_only_after_provider_confirms(client):
    tenant, headers = _owner(client, 'v1-cancel@example.test', 'v1-cancel')
    with client.application.app_context():
        _active_subscription(client, tenant)
    remote = {'id': 'mp-sub-v1', 'external_reference': 'ref-mp-sub-v1', 'status': 'authorized'}
    with patch(API, return_value=remote):  # provider did NOT cancel
        r = client.post('/api/v1/billing/mercadopago/cancel', headers=headers)
    assert r.status_code == 502
    with client.application.app_context():
        assert db.session.query(TenantSubscription).one().status == 'active'
    remote = dict(remote, status='cancelled')
    with patch(API, return_value=remote) as provider:
        r = client.post('/api/v1/billing/mercadopago/cancel', headers=headers)
    assert r.status_code == 200, r.json
    methods = [call.args[0] for call in provider.call_args_list]
    assert methods[0] == 'PUT' and 'GET' in methods
    with client.application.app_context():
        sub = db.session.query(TenantSubscription).one()
        assert sub.status == 'canceled'
        audit = db.session.scalar(select(SubscriptionAudit).where(SubscriptionAudit.action == 'mp_canceled'))
        assert audit.actor_id is not None


def test_cancel_without_subscription_is_404(client):
    _, headers = _owner(client, 'v1-nosub@example.test', 'v1-nosub')
    assert client.post('/api/v1/billing/mercadopago/cancel', headers=headers).status_code == 404


def test_cancel_is_tenant_isolated(client):
    tenant_a, _ = _owner(client, 'v1-iso-a@example.test', 'v1-iso-a')
    _, headers_b = _owner(client, 'v1-iso-b@example.test', 'v1-iso-b')
    with client.application.app_context():
        _active_subscription(client, tenant_a)
    with patch(API) as provider:
        assert client.post('/api/v1/billing/mercadopago/cancel', headers=headers_b).status_code == 404
        provider.assert_not_called()
    # Tenant B cannot act on tenant A by spoofing the header.
    spoof = dict(headers_b, **{'X-Tenant-ID': str(tenant_a)})
    assert client.post('/api/v1/billing/mercadopago/cancel', headers=spoof).status_code == 403


def test_checkout_requires_billing_manage(client):
    tenant, headers = _owner(client, 'v1-perm@example.test', 'v1-perm')
    with client.application.app_context():
        price = _price()
        # Second member with a role lacking billing.manage.
        role = Role(tenant_id=tenant, name='viewer')
        db.session.add(role)
        db.session.flush()
        perm = db.session.scalar(select(Permission).where(Permission.code == 'tenant.read'))
        db.session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        db.session.commit()
        price_id, role_id = price.id, role.id
    register(client, 'v1-viewer@example.test', 'v1-viewer-co')
    with client.application.app_context():
        viewer = db.session.scalar(select(User).where(User.email == 'v1-viewer@example.test'))
        db.session.add(Membership(tenant_id=tenant, user_id=viewer.id, role_id=role_id))
        db.session.commit()
    viewer_headers = {'Authorization': 'Bearer ' + token(client, 'v1-viewer@example.test'), 'X-Tenant-ID': str(tenant)}
    body = {'plan_price_id': price_id, 'payer_email': 'pay@example.test'}
    with patch(API) as provider:
        assert client.post('/api/v1/billing/mercadopago/checkout', headers=viewer_headers, json=body).status_code == 403
        provider.assert_not_called()
    assert client.get('/api/v1/billing/mercadopago/checkout/latest', headers=viewer_headers).status_code == 200
    perms = client.get('/api/v1/auth/permissions', headers=headers).json['permissions']
    assert 'billing.manage' in perms


def test_checkout_ignores_client_supplied_amount(client):
    tenant, headers = _owner(client, 'v1-price@example.test', 'v1-price')
    client.application.config.update(MP_ACCESS_TOKEN='t', MP_BACK_URL='https://example.test/billing/return')
    with client.application.app_context():
        price_id = _price('699.00').id
    body = {'plan_price_id': price_id, 'payer_email': 'pay@example.test', 'amount': '1.00'}
    with patch(API) as provider:
        assert client.post('/api/v1/billing/mercadopago/checkout', headers=headers, json=body).status_code == 422
        provider.assert_not_called()
    body.pop('amount')
    with patch(API, return_value={'id': 'mp-x', 'init_point': 'https://mp.example/x'}) as provider:
        assert client.post('/api/v1/billing/mercadopago/checkout', headers=headers, json=body).status_code == 201
    sent = provider.call_args.args[2]
    assert sent['auto_recurring']['transaction_amount'] == 699.0
    latest = client.get('/api/v1/billing/mercadopago/checkout/latest', headers=headers).json
    assert latest['checkout']['status'] == 'pending'


# ------------------------------------------------------------------
# Webhook reconciliation issues
# ------------------------------------------------------------------

def _signed(app, resource_id, request_id):
    ts = str(int(time.time()))
    digest = hmac.new(app.config['MP_WEBHOOK_SECRET'].encode(),
                      f'id:{resource_id};request-id:{request_id};ts:{ts};'.encode(), hashlib.sha256).hexdigest()
    return {'x-signature': f'ts={ts},v1={digest}', 'x-request-id': request_id}


def test_unreconciled_webhook_is_recorded_then_resolved(client):
    app = client.application
    app.config['MP_WEBHOOK_SECRET'] = 'webhook-secret-for-tests'
    tenant, _ = _owner(client, 'v1-hook@example.test', 'v1-hook')
    with app.app_context():
        _checkout(tenant, _price())
    url = '/api/v1/billing/mercadopago/webhook?type=subscription_authorized_payment&data.id=inv-hook'
    with patch(API, return_value=_invoice('inv-hook', charge=None)):
        assert client.post(url, headers=_signed(app, 'inv-hook', 'r1')).status_code == 503
    with app.app_context():
        issue = db.session.query(MPReconciliationIssue).one()
        assert issue.reason == 'not_reconciled' and issue.resolved_at is None
    with patch(API, return_value=_invoice('inv-hook')):
        assert client.post(url, headers=_signed(app, 'inv-hook', 'r2')).status_code == 200
    with app.app_context():
        assert db.session.query(MPReconciliationIssue).one().resolved_at is not None


def test_webhook_rejects_bad_signature(client):
    app = client.application
    app.config['MP_WEBHOOK_SECRET'] = 'webhook-secret-for-tests'
    url = '/api/v1/billing/mercadopago/webhook?type=subscription_authorized_payment&data.id=inv-x'
    headers = _signed(app, 'inv-x', 'r1')
    headers['x-request-id'] = 'tampered'
    with patch(API) as provider:
        assert client.post(url, headers=headers).status_code == 401
        provider.assert_not_called()


# ------------------------------------------------------------------
# Operator panel: pricing & overview
# ------------------------------------------------------------------

@pytest.fixture
def operator(client):
    _owner(client, 'v1-op@example.test', 'v1-op')
    tenant, tenant_headers = _owner(client, 'v1-ten@example.test', 'v1-ten')
    with client.application.app_context():
        op_user = db.session.scalar(select(User).where(User.email == 'v1-op@example.test'))
        client.application.config['BILLING_OPERATOR_USER_IDS'] = frozenset({op_user.id})
        price = _price()
        price_id = price.id
    return {'headers': {'Authorization': 'Bearer ' + token(client, 'v1-op@example.test')},
            'tenant_headers': tenant_headers, 'tenant': tenant, 'price_id': price_id}


def test_price_admin_is_operator_only(client, operator):
    for method, url in [('get', '/api/v1/billing/admin/prices'), ('get', '/api/v1/billing/admin/subscriptions'),
                        ('get', '/api/v1/billing/admin/me'), ('get', '/api/v1/billing/admin/reconciliation-issues'),
                        ('post', f"/api/v1/billing/admin/prices/{operator['price_id']}/deactivate")]:
        assert getattr(client, method)(url, headers=operator['tenant_headers']).status_code == 403
        assert getattr(client, method)(url).status_code == 401
    assert client.get('/api/v1/billing/admin/me', headers=operator['headers']).status_code == 200


def test_reprice_versions_and_audits(client, operator):
    h, pid = operator['headers'], operator['price_id']
    for bad in ['0', '-1', '1.234', 'abc', '1e3', '9999999']:
        assert client.post(f'/api/v1/billing/admin/prices/{pid}/reprice', headers=h, json={'amount': bad}).status_code == 422
    r = client.post(f'/api/v1/billing/admin/prices/{pid}/reprice', headers=h, json={'amount': '349.00'})
    assert r.status_code == 201, r.json
    new_id = r.json['price']['id']
    assert r.json['price']['version'] == 2
    assert client.post(f'/api/v1/billing/admin/prices/{pid}/reprice', headers=h, json={'amount': '1.00'}).status_code == 409
    history = client.get('/api/v1/billing/admin/prices?history=1', headers=h).json['items'][0]['prices']
    assert {p['id']: p['active'] for p in history} == {pid: False, new_id: True}
    audits = client.get('/api/v1/billing/admin/prices/audits', headers=h).json
    assert audits['total'] == 1 and audits['items'][0]['old_amount'] == '299.00'
    assert audits['items'][0]['new_amount'] == '349.00' and audits['items'][0]['actor_id']
    # Tenants now see only the new price.
    plans = client.get('/api/v1/billing/plans', headers=operator['tenant_headers']).json['items']
    assert [p['id'] for p in plans[0]['prices']] == [new_id]


def test_reprice_never_touches_existing_subscription(client, operator):
    pid = operator['price_id']
    with client.application.app_context():
        price = db.session.get(BillingPlanPrice, pid)
        _checkout(operator['tenant'], price)
        with patch(API, return_value=_invoice('inv-keep')):
            assert reconcile_payment('inv-keep') is True
    r = client.post(f'/api/v1/billing/admin/prices/{pid}/reprice', headers=operator['headers'], json={'amount': '399.00'})
    assert r.status_code == 201
    with client.application.app_context():
        sub = db.session.query(TenantSubscription).one()
        assert sub.plan_price_id == pid
        assert db.session.get(BillingPlanPrice, pid).amount == Decimal('299.00')
        # A renewal at the contracted amount is still accepted.
        with patch(API, return_value=_invoice('inv-keep-2')):
            assert reconcile_payment('inv-keep-2') is True
    subs = client.get('/api/v1/billing/admin/subscriptions', headers=operator['headers']).json
    assert subs['total'] == 1 and subs['items'][0]['amount'] == '299.00' and subs['items'][0]['price_version'] == 1
    pays = client.get(f"/api/v1/billing/admin/tenants/{operator['tenant']}/payments", headers=operator['headers']).json
    assert len(pays['items']) == 2


def test_activate_keeps_single_active_price(client, operator):
    h, pid = operator['headers'], operator['price_id']
    new_id = client.post(f'/api/v1/billing/admin/prices/{pid}/reprice', headers=h, json={'amount': '349.00'}).json['price']['id']
    r = client.post(f'/api/v1/billing/admin/prices/{pid}/activate', headers=h)
    assert r.status_code == 200 and r.json['price']['active'] is True
    with client.application.app_context():
        assert db.session.get(BillingPlanPrice, new_id).active is False
        assert db.session.query(BillingPriceAudit).filter_by(action='activate').count() == 1
    assert client.post(f'/api/v1/billing/admin/prices/{pid}/deactivate', headers=h).status_code == 200
    assert client.post(f'/api/v1/billing/admin/prices/{pid}/deactivate', headers=h).status_code == 409


# ------------------------------------------------------------------
# Production configuration & HTTP hardening
# ------------------------------------------------------------------

def test_production_config_fails_closed(monkeypatch):
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                      'SECRET_KEY': 'k', 'JWT_SECRET_KEY': 'k', 'CHECK_DB_ON_STARTUP': False})
    for key in ('SECRET_KEY', 'JWT_SECRET_KEY', 'SIGNATURE_OTP_SECRET', 'CORS_ORIGINS', 'FRONTEND_PUBLIC_URL'):
        monkeypatch.delenv(key, raising=False)
    app.config.update(SECRET_KEY='dev-only-not-for-production', MP_ACCESS_TOKEN='', MP_BACK_URL='http://x')
    with pytest.raises(RuntimeError) as exc:
        _validate_production_config(app)
    message = str(exc.value)
    for expected in ('SECRET_KEY', 'MP_ACCESS_TOKEN', 'MP_BACK_URL', 'CORS_ORIGINS', 'RATELIMIT_STORAGE_URI'):
        assert expected in message
    strong = 'x' * 40
    for key in ('SECRET_KEY', 'JWT_SECRET_KEY', 'SIGNATURE_OTP_SECRET'):
        monkeypatch.setenv(key, strong)
    monkeypatch.setenv('CORS_ORIGINS', 'https://app.example.com')
    monkeypatch.setenv('FRONTEND_PUBLIC_URL', 'https://app.example.com')
    app.config.update(MP_ACCESS_TOKEN='APP_USR-x', MP_WEBHOOK_SECRET='y' * 32,
                      MP_BACK_URL='https://app.example.com/billing/return',
                      RATELIMIT_STORAGE_URI='redis://cache:6379/0')
    _validate_production_config(app)


def test_security_headers(client):
    r = client.get('/api/v1/health')
    assert r.headers['X-Content-Type-Options'] == 'nosniff'
    assert r.headers['X-Frame-Options'] == 'DENY'


def test_login_rate_limit_when_enabled():
    from app.extensions import limiter
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                      'SECRET_KEY': 'k', 'JWT_SECRET_KEY': 'k', 'CHECK_DB_ON_STARTUP': False,
                      'RATELIMIT_ENABLED': True, 'RATELIMIT_LOGIN': '3 per minute'})
    limiter.init_app(app)
    with app.app_context():
        db.create_all()
        c = app.test_client()
        codes = [c.post('/api/v1/auth/login', json={'email': 'a@b.c', 'password': 'x'}).status_code for _ in range(4)]
        db.session.remove()
        db.drop_all()
    assert codes[:3] == [401, 401, 401] and codes[3] == 429


def test_registration_rejects_invalid_slug_and_email(client):
    base = {'email': 'ok@example.test', 'password': 'a-very-long-password', 'company_name': 'Empresa'}
    assert client.post('/api/v1/auth/register', json=dict(base, slug='Bad Slug!')).status_code == 400
    assert client.post('/api/v1/auth/register', json=dict(base, slug='ok-slug', email='not-an-email')).status_code == 400
    assert client.post('/api/v1/auth/register', json=dict(base, slug='ok-slug')).status_code == 201


def test_proxy_fix_uses_real_client_ip(monkeypatch):
    from flask import request
    monkeypatch.setenv('TRUSTED_PROXY_COUNT', '1')
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                      'SECRET_KEY': 'k', 'JWT_SECRET_KEY': 'k', 'CHECK_DB_ON_STARTUP': False})
    with app.test_request_context('/', headers={'X-Forwarded-For': '203.0.113.7'},
                                  environ_base={'REMOTE_ADDR': '10.0.0.2'}):
        app.wsgi_app(request.environ, lambda *a, **k: None)
        assert request.environ['REMOTE_ADDR'] == '203.0.113.7'



# ------------------------------------------------------------------
# Política comercial v1.0: nivel gratuito y cancelación al fin del periodo
# ------------------------------------------------------------------

def test_free_tier_applies_without_subscription(client):
    from app.services.billing.catalog_seed import seed_free_tier
    from app.services.billing.entitlements_service import entitlement
    tenant, headers = _owner(client, 'v1-free@example.test', 'v1-free')
    with client.application.app_context():
        assert entitlement(tenant, 'clients')['reason'] == 'not_subscribed'  # fail-closed sin sembrar
        assert seed_free_tier() == {'plans': 1, 'entitlements': 7}
        assert seed_free_tier() == {'plans': 0, 'entitlements': 0}
        decision = entitlement(tenant, 'clients')
        assert decision['allowed'] is True and decision['tier'] == 'free' and decision['limit'] == 25
        assert entitlement(tenant, 'advanced_reports')['reason'] == 'feature_disabled'
    plans = client.get('/api/v1/billing/plans', headers=headers).json['items']
    assert all(p['code'] != 'free' for p in plans)
    usage = client.get('/api/v1/billing/usage', headers=headers).json
    assert usage['tier'] == 'free' and any(i['feature_code'] == 'clients' for i in usage['items'])


def test_free_tier_limit_enforced_on_create(client):
    from app.services.billing.catalog_seed import seed_free_tier
    from app.models.billing import BillingPlanEntitlement
    tenant, headers = _owner(client, 'v1-free-lim@example.test', 'v1-free-lim')
    with client.application.app_context():
        seed_free_tier()
        free = db.session.scalar(select(BillingPlan).where(BillingPlan.code == 'free'))
        ent = db.session.scalar(select(BillingPlanEntitlement).where(
            BillingPlanEntitlement.plan_id == free.id, BillingPlanEntitlement.feature_code == 'clients'))
        ent.limit_value = 1
        db.session.commit()
    client.application.config['BILLING_ENFORCE_ENTITLEMENTS'] = True
    try:
        body = {'client_type': 'individual', 'first_name': 'Ana', 'last_name': 'Uno', 'email': 'ana1@example.test'}
        first = client.post('/api/v1/clients', headers=headers, json=body)
        assert first.status_code == 201, first.json
        second = client.post('/api/v1/clients', headers=headers, json=dict(body, email='ana2@example.test'))
        assert second.status_code == 403
        assert second.json['reason'] == 'limit_reached' and second.json['tier'] == 'free'
    finally:
        client.application.config['BILLING_ENFORCE_ENTITLEMENTS'] = False


def test_canceled_subscription_keeps_access_until_period_end(client):
    from datetime import timedelta
    from app.services.billing.entitlements_service import entitlement
    from app.models.billing import BillingPlanEntitlement
    tenant, headers = _owner(client, 'v1-cend@example.test', 'v1-cend')
    with client.application.app_context():
        price = _price()
        db.session.add(BillingPlanEntitlement(plan_id=price.plan_id, feature_code='clients', limit_value=100))
        db.session.commit()
        _checkout(tenant, price)
        with patch(API, return_value=_invoice('inv-cend')):
            assert reconcile_payment('inv-cend') is True
    remote = {'id': 'mp-sub-v1', 'external_reference': 'ref-mp-sub-v1', 'status': 'cancelled'}
    with patch(API, return_value=remote):
        assert client.post('/api/v1/billing/mercadopago/cancel', headers=headers).status_code == 200
    with client.application.app_context():
        sub = db.session.query(TenantSubscription).one()
        assert sub.status == 'canceled' and sub.ended_at == sub.current_period_end
        during = entitlement(tenant, 'clients')
        assert during['allowed'] is True and during['tier'] == 'paid' and during['limit'] == 100
        after = entitlement(tenant, 'clients', at=sub.current_period_end + timedelta(seconds=1))
        assert after['allowed'] is False and after['reason'] == 'subscription_inactive'



def test_preapproval_frequency_by_interval(client):
    tenant, headers = _owner(client, 'v1-freq@example.test', 'v1-freq')
    client.application.config.update(MP_ACCESS_TOKEN='t', MP_BACK_URL='https://example.test/billing/return')
    with client.application.app_context():
        annual_id = _price('2511.60', interval='year', code='v1-annual').id
    with patch(API, return_value={'id': 'mp-annual', 'init_point': 'https://mp.example/a'}) as provider:
        r = client.post('/api/v1/billing/mercadopago/checkout', headers=headers,
                        json={'plan_price_id': annual_id, 'payer_email': 'buyer@example.test'})
    assert r.status_code == 201, r.json
    recurring = provider.call_args.args[2]['auto_recurring']
    assert recurring['frequency_type'] == 'months' and recurring['frequency'] == 12
    assert recurring['transaction_amount'] == 2511.6


def test_provider_error_detail_is_sanitized():
    import io
    import urllib.error
    from app.services.billing.mercadopago_client import _safe_error_detail
    body = (b'{"message":"Invalid payer_email buyer@example.com","status":400,'
            b'"cause":[{"code":"123","description":"token APP_USR-1234567890abcdefghijklmnopqrstuvwxyz"}]}')
    exc = urllib.error.HTTPError('https://api.mercadopago.com/preapproval', 400, 'Bad Request', {}, io.BytesIO(body))
    detail = _safe_error_detail(exc)
    assert 'Invalid payer_email' in detail and 'cause=123' in detail
    assert 'buyer@example.com' not in detail and 'abcdefghijklmnop' not in detail
