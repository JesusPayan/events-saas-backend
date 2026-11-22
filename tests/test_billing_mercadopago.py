import hashlib
import hmac
from decimal import Decimal
from unittest.mock import patch
from app.extensions import db
from app.models.billing import BillingPlan, BillingPlanPrice, TenantSubscription, SubscriptionAudit
from app.models.mercadopago import MPPayment
from app.services.billing.mercadopago_service import signature_valid, reconcile_payment
from tests.test_identity import client, register, token

def test_signature_valid_and_invalid(client):
    app = client.application
    app.config['MP_WEBHOOK_SECRET'] = 'secret'
    import time
    ts = str(int(time.time() * 1000))
    request_id, resource_id = 'req-123', '12345'
    digest = hmac.new(b'secret', f'id:{resource_id};request-id:{request_id};ts:{ts};'.encode(), hashlib.sha256).hexdigest()
    with app.app_context():
        assert signature_valid(f'ts={ts},v1={digest}', request_id, resource_id)
        assert not signature_valid('ts=' + ts + ',v1=' + '0'*64, request_id, resource_id)
        assert not signature_valid(f'ts=1,v1={digest}', request_id, resource_id)

def test_checkout_auth_and_provider_confirmed_payment(client):
    r = register(client, 'mp-owner@example.test', 'mp-owner')
    assert r.status_code == 201
    tenant = r.json['tenant_id']
    headers = {'Authorization': 'Bearer ' + token(client, 'mp-owner@example.test'), 'X-Tenant-ID': str(tenant)}
    with client.application.app_context():
        plan = BillingPlan(code='mp-basic', name='Basic', active=True)
        db.session.add(plan); db.session.flush()
        price = BillingPlanPrice(plan_id=plan.id, currency='MXN', billing_interval='month', amount=Decimal('299.00'), active=True, version=1)
        db.session.add(price); db.session.commit(); price_id = price.id
    path = '/api/v1/billing/mercadopago/checkout'
    assert client.post(path, json={'plan_price_id': price_id, 'payer_email':'mp@example.test'}).status_code == 401
    client.application.config['MP_ACCESS_TOKEN'] = 'test-token'
    client.application.config['MP_BACK_URL'] = 'https://example.test/billing/return'
    with patch('app.services.billing.mercadopago_service.api', return_value={'id':'mp-sub-123','init_point':'https://www.mercadopago.com/checkout'}):
        result = client.post(path, headers=headers, json={'plan_price_id': price_id, 'payer_email':'mp@example.test'})
    assert result.status_code == 201, result.json
    with client.application.app_context():
        assert db.session.query(TenantSubscription).count() == 0
        payment = {'id':'pay-1', 'preapproval_id':'mp-sub-123', 'transaction_amount':299, 'currency_id':'MXN', 'status':'approved'}
        with patch('app.services.billing.mercadopago_service.api', return_value=payment):
            assert reconcile_payment('pay-1') is True
            assert reconcile_payment('pay-1') is True
        assert db.session.query(TenantSubscription).count() == 1
        assert db.session.query(MPPayment).count() == 1
        assert db.session.query(SubscriptionAudit).count() == 1
        assert db.session.query(TenantSubscription).first().status == 'active'
