"""Webhook smoke tests with signed requests; no external network calls."""
import hashlib
import hmac
import time
import hashlib
from unittest.mock import patch
from app.extensions import db
from app.models.mercadopago import MPWebhookEvent
from tests.test_identity import client


def _signed(resource_id='mp123', kind='subscription_authorized_payment', secret='unit-secret'):
    ts = str(int(time.time() * 1000))
    request_id = 'webhook-test-123'
    manifest = f'id:{resource_id.lower()};request-id:{request_id};ts:{ts};'
    digest = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return (f'/api/v1/billing/mercadopago/webhook?type={kind}&data.id={resource_id}',
            {'x-request-id': request_id, 'x-signature': f'ts={ts},v1={digest}'})


def test_webhook_rejects_unsigned(client):
    client.application.config['MP_WEBHOOK_SECRET'] = 'unit-secret'
    assert client.post('/api/v1/billing/mercadopago/webhook?type=subscription_authorized_payment&data.id=mp123').status_code == 401


def test_webhook_persists_once_and_deduplicates(client):
    client.application.config['MP_WEBHOOK_SECRET'] = 'unit-secret'
    url, headers = _signed('unique-mp-dedup-42')
    with patch('app.api.mercadopago.reconcile_payment', return_value=True) as reconcile:
        first = client.post(url, headers=headers)
        second = client.post(url, headers=headers)
    assert first.status_code == 200, first.json
    assert second.status_code == 200 and second.json['duplicate'] is True
    reconcile.assert_called_once_with('unique-mp-dedup-42')
    with client.application.app_context():
        assert db.session.query(MPWebhookEvent).filter_by(event_key=hashlib.sha256('subscription_authorized_payment:unique-mp-dedup-42:webhook-test-123'.encode()).hexdigest()).count() == 1


def test_webhook_failure_not_recorded_and_can_retry(client):
    client.application.config['MP_WEBHOOK_SECRET'] = 'unit-secret'
    url, headers = _signed('unique-mp-retry-43')
    with patch('app.api.mercadopago.reconcile_payment', side_effect=[False, True]) as reconcile:
        assert client.post(url, headers=headers).status_code == 503
        assert client.post(url, headers=headers).status_code == 200
    assert reconcile.call_count == 2


def test_new_request_id_rechecks_same_resource(client):
    client.application.config['MP_WEBHOOK_SECRET'] = 'unit-secret'
    url, headers = _signed('unique-mp-status-change-51')
    with patch('app.api.mercadopago.reconcile_payment', return_value=True) as reconcile:
        assert client.post(url, headers=headers).status_code == 200
        other_url, other_headers = _signed('unique-mp-status-change-51')
        other_headers['x-request-id'] = 'second-delivery-456'
        ts = other_headers['x-signature'].split(',')[0].split('=', 1)[1]
        manifest = f'id:unique-mp-status-change-51;request-id:second-delivery-456;ts:{ts};'
        digest = hmac.new(b'unit-secret', manifest.encode(), hashlib.sha256).hexdigest()
        other_headers['x-signature'] = f'ts={ts},v1={digest}'
        assert client.post(other_url, headers=other_headers).status_code == 200
    assert reconcile.call_count == 2
