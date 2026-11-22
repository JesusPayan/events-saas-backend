"""Mocked provider search; uses the existing project SQLite test fixture."""
from unittest.mock import patch
from app.extensions import db
from app.services.billing.mercadopago_discovery import discover_invoices
from tests.test_billing_mp_production import _setup
from tests.test_identity import client


def _page(method, path):
    assert method == 'GET' and '/authorized_payments/search?' in path
    return {'paging': {'total': 2}, 'results': [
        {'id': 10001, 'preapproval_id': 'renewal-sub', 'payment': {'status': 'approved'}},
        {'id': 10002, 'preapproval_id': 'renewal-sub', 'payment': {'status': 'rejected'}},
    ]}


def test_discovery_report_only(client):
    _setup(client)
    with client.application.app_context():
        with patch('app.services.billing.mercadopago_discovery.api', side_effect=_page), \
             patch('app.services.billing.mercadopago_discovery.reconcile_payment') as reconcile:
            report = discover_invoices(page_size=20)
        assert report['missing'] == 1
        assert report['applied'] == 0
        reconcile.assert_not_called()


def test_discovery_apply_only_approved(client):
    _setup(client)
    with client.application.app_context():
        with patch('app.services.billing.mercadopago_discovery.api', side_effect=_page), \
             patch('app.services.billing.mercadopago_discovery.reconcile_payment', return_value=True) as reconcile:
            report = discover_invoices(apply=True)
        assert report['applied'] == 1
        reconcile.assert_called_once_with('10001')


def test_discovery_rejects_invalid_limits(client):
    with client.application.app_context():
        try:
            discover_invoices(limit=0)
        except ValueError:
            pass
        else:
            raise AssertionError('must reject invalid limit')
