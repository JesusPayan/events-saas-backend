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


def test_discovery_default_omits_limit_and_pages_by_offset(client):
    """Mercado Pago rejected limit=20 (400 'Invalid value for limit'): by default
    the request carries no limit and pages with the provider's own page size."""
    from unittest.mock import patch
    from decimal import Decimal
    from app.extensions import db
    from app.models.billing import BillingPlan, BillingPlanPrice
    from app.models.mercadopago import MPCheckout
    from app.services.billing.mercadopago_discovery import discover_invoices
    from tests.test_identity import register
    tenant = register(client, 'disc-nolimit@example.test', 'disc-nolimit').json['tenant_id']
    with client.application.app_context():
        plan = BillingPlan(code='disc-nolimit', name='P', active=True)
        db.session.add(plan); db.session.flush()
        price = BillingPlanPrice(plan_id=plan.id, currency='MXN', billing_interval='month', amount=Decimal('299'), active=True)
        db.session.add(price); db.session.flush()
        db.session.add(MPCheckout(tenant_id=tenant, plan_price_id=price.id, payer_email='b@example.test',
                                  external_reference='ref-nolimit', provider_subscription_id='sub-nolimit', status='authorized'))
        db.session.commit()
        paths = []
        pages = [
            {'results': [{'id': 101, 'preapproval_id': 'sub-nolimit', 'payment': {'status': 'rejected'}}], 'paging': {'total': 2}},
            {'results': [{'id': 102, 'preapproval_id': 'sub-nolimit', 'payment': {'status': 'rejected'}}], 'paging': {'total': 2}},
        ]
        def fake(method, path, payload=None, **kw):
            paths.append(path)
            return pages[len(paths) - 1]
        with patch('app.services.billing.mercadopago_discovery.api', side_effect=fake):
            report = discover_invoices()
        assert all('limit=' not in p for p in paths)
        assert 'offset' not in paths[0] and 'offset=1' in paths[1]
        assert report['invoices'] == 2 and report['incomplete'] == 0 and report['errors'] == 0
