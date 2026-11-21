"""BILL-01.3.4: operator-only billing workflow and tenant isolation.

SQLite in-memory fixture from existing identity tests; never touches MySQL.
"""
import pytest
from sqlalchemy import select
from app.extensions import db
from app.models.identity import User
from app.models.billing import BillingPlan, BillingPlanPrice, SubscriptionAudit, TenantSubscription
from tests.test_identity import client, register, token


@pytest.fixture
def case(client):
    a = register(client, 'admin-bill-a@example.test', 'admin-bill-a')
    b = register(client, 'admin-bill-b@example.test', 'admin-bill-b')
    assert a.status_code == b.status_code == 201
    with client.application.app_context():
        user_a = db.session.scalar(select(User).where(User.email == 'admin-bill-a@example.test'))
        client.application.config['BILLING_OPERATOR_USER_IDS'] = (user_a.id,)
        plan = BillingPlan(code='basic', name='Basic', active=True)
        db.session.add(plan)
        db.session.flush()
        prices = []
        for interval, amount in [('month', 299), ('year', 2511.60)]:
            price = BillingPlanPrice(plan_id=plan.id, currency='MXN', billing_interval=interval, amount=amount, version=1, active=True)
            db.session.add(price)
            db.session.flush()
            prices.append(price.id)
        db.session.commit()
    return {'client': client, 'a': a.json['tenant_id'], 'b': b.json['tenant_id'],
            'operator': {'Authorization': 'Bearer ' + token(client, 'admin-bill-a@example.test')},
            'ordinary': {'Authorization': 'Bearer ' + token(client, 'admin-bill-b@example.test')},
            'prices': prices}


def path(tenant):
    return f'/api/v1/billing/admin/tenants/{tenant}/subscriptions'


def assign(c, tenant, headers, price, **kwargs):
    return c.post(path(tenant), headers=headers, json={'plan_price_id': price, **kwargs})


def test_fail_closed_without_operator_config(case):
    c = case['client']
    c.application.config.pop('BILLING_OPERATOR_USER_IDS')
    assert assign(c, case['a'], case['operator'], case['prices'][0]).status_code == 403


def test_requires_auth(case):
    assert assign(case['client'], case['a'], {}, case['prices'][0]).status_code == 401


def test_tenant_owner_cannot_activate_or_assign(case):
    assert assign(case['client'], case['b'], case['ordinary'], case['prices'][0]).status_code == 403
    assert assign(case['client'], case['a'], case['operator'], case['prices'][0], status='active').status_code == 422


def test_assign_and_audit(case):
    c = case['client']
    r = assign(c, case['a'], case['operator'], case['prices'][0], trial_days=14)
    assert r.status_code == 201, r.json
    assert r.json['subscription']['status'] == 'trialing'
    sid = r.json['subscription']['id']
    audit = c.get(f'{path(case["a"])}/{sid}/audits', headers=case['operator'])
    assert audit.status_code == 200
    assert [(x['action'], x['new_status']) for x in audit.json['items']] == [('assigned', 'trialing')]


def test_duplicate_assignment_rejected(case):
    c = case['client']
    assert assign(c, case['a'], case['operator'], case['prices'][0]).status_code == 201
    assert assign(c, case['a'], case['operator'], case['prices'][0]).status_code == 409


def test_plan_change_preserves_trial_and_audits(case):
    c = case['client']
    sid = assign(c, case['a'], case['operator'], case['prices'][0]).json['subscription']['id']
    r = c.patch(f'{path(case["a"])}/{sid}/plan', headers=case['operator'], json={'plan_price_id': case['prices'][1]})
    assert r.status_code == 200, r.json
    assert r.json['subscription']['status'] == 'trialing'
    assert r.json['subscription']['plan_price_id'] == case['prices'][1]
    audits = c.get(f'{path(case["a"])}/{sid}/audits', headers=case['operator']).json['items']
    assert [a['action'] for a in audits] == ['assigned', 'plan_changed']


def test_cancel_and_reassign(case):
    c = case['client']
    sid = assign(c, case['a'], case['operator'], case['prices'][0]).json['subscription']['id']
    r = c.post(f'{path(case["a"])}/{sid}/cancel', headers=case['operator'])
    assert r.status_code == 200
    assert r.json['subscription']['status'] == 'canceled'
    assert c.post(f'{path(case["a"])}/{sid}/cancel', headers=case['operator']).status_code == 409
    assert assign(c, case['a'], case['operator'], case['prices'][0]).status_code == 201


def test_cross_tenant_id_isolation(case):
    c = case['client']
    sid = assign(c, case['a'], case['operator'], case['prices'][0]).json['subscription']['id']
    assert c.patch(f'{path(case["b"])}/{sid}/plan', headers=case['operator'], json={'plan_price_id': case['prices'][1]}).status_code == 404
    assert c.post(f'{path(case["b"])}/{sid}/cancel', headers=case['operator']).status_code == 404
    assert c.get(f'{path(case["b"])}/{sid}/audits', headers=case['operator']).status_code == 404
    with c.application.app_context():
        assert db.session.get(TenantSubscription, sid).status == 'trialing'


def test_invalid_price_and_payload(case):
    c = case['client']
    assert assign(c, case['a'], case['operator'], 999999).status_code == 422
    assert assign(c, case['a'], case['operator'], case['prices'][0], provider='fake').status_code == 422
    assert assign(c, case['a'], case['operator'], case['prices'][0], trial_days=31).status_code == 422
    assert c.post(path(case['a']), headers=case['operator'], data='not-json', content_type='application/json').status_code == 400


def test_provider_managed_cannot_be_changed(case):
    c = case['client']
    sid = assign(c, case['a'], case['operator'], case['prices'][0]).json['subscription']['id']
    with c.application.app_context():
        sub = db.session.get(TenantSubscription, sid)
        sub.provider = 'stripe'
        sub.provider_subscription_id = 'sub_example'
        db.session.commit()
    assert c.patch(f'{path(case["a"])}/{sid}/plan', headers=case['operator'], json={'plan_price_id': case['prices'][1]}).status_code == 409
    assert c.post(f'{path(case["a"])}/{sid}/cancel', headers=case['operator']).status_code == 409
