"""BILL-01.2: security, catalog, subscription and tenant usage API tests.

Uses the project's existing SQLite in-memory client fixture; never writes to MySQL.
"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models.billing import BillingPlan, BillingPlanPrice, BillingPlanEntitlement, TenantSubscription
from app.models.identity import Membership, Permission, Role, RolePermission
from tests.test_identity import client, register, token

ENDPOINTS = ("/api/v1/billing/plans", "/api/v1/billing/subscription", "/api/v1/billing/usage")


@pytest.fixture
def tenants(client):
    a = register(client, "bill-a@example.test", "bill-a")
    b = register(client, "bill-b@example.test", "bill-b")
    assert a.status_code == 201, a.get_json()
    assert b.status_code == 201, b.get_json()
    ta, tb = a.json["tenant_id"], b.json["tenant_id"]
    return {
        "client": client, "a": ta, "b": tb,
        "ha": {"Authorization": f"Bearer {token(client, 'bill-a@example.test')}", "X-Tenant-ID": str(ta)},
        "hb": {"Authorization": f"Bearer {token(client, 'bill-b@example.test')}", "X-Tenant-ID": str(tb)},
    }


def add_plan(code="basic", active=True):
    plan = BillingPlan(code=code, name=code.title(), active=active)
    db.session.add(plan)
    db.session.flush()
    price = BillingPlanPrice(plan_id=plan.id, currency="MXN", billing_interval="month", amount=Decimal("199.00"), version=1, active=True)
    db.session.add(price)
    db.session.flush()
    for feature, limit in (("members", 3), ("clients", 5), ("events", 10), ("custom_feature", None)):
        db.session.add(BillingPlanEntitlement(plan_id=plan.id, feature_code=feature, limit_value=limit))
    db.session.commit()
    return plan.id, price.id


def subscribe(tenant_id, price_id, status="active"):
    sub = TenantSubscription(tenant_id=tenant_id, plan_price_id=price_id, status=status)
    db.session.add(sub)
    db.session.commit()
    return sub.id


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_requires_authentication(client, endpoint):
    r = client.get(endpoint, headers={"X-Tenant-ID": "1"})
    assert r.status_code == 401
    assert r.json["error"] == "authentication_required"


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_rejects_invalid_token(client, endpoint):
    r = client.get(endpoint, headers={"Authorization": "Bearer invalid", "X-Tenant-ID": "1"})
    assert r.status_code == 401
    assert r.json["error"] == "invalid_token"


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_requires_tenant_header(tenants, endpoint):
    headers = {"Authorization": tenants["ha"]["Authorization"]}
    r = tenants["client"].get(endpoint, headers=headers)
    assert r.status_code == 400
    assert r.json["error"] == "tenant_required"


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_rejects_cross_tenant_membership(tenants, endpoint):
    headers = {**tenants["ha"], "X-Tenant-ID": str(tenants["b"])}
    r = tenants["client"].get(endpoint, headers=headers)
    assert r.status_code == 403


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_rejects_inactive_membership(tenants, endpoint):
    with tenants["client"].application.app_context():
        member = db.session.scalar(select(Membership).where(Membership.tenant_id == tenants["a"]))
        member.status = "inactive"
        db.session.commit()
    r = tenants["client"].get(endpoint, headers=tenants["ha"])
    assert r.status_code == 403


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_rejects_role_without_tenant_read(tenants, endpoint):
    with tenants["client"].application.app_context():
        role = Role(tenant_id=tenants["a"], name="billing_no_read")
        db.session.add(role)
        db.session.flush()
        member = db.session.scalar(select(Membership).where(Membership.tenant_id == tenants["a"]))
        member.role_id = role.id
        db.session.commit()
    r = tenants["client"].get(endpoint, headers=tenants["ha"])
    assert r.status_code == 403


def test_empty_catalog_and_unsubscribed_state(tenants):
    c, h = tenants["client"], tenants["ha"]
    assert c.get(ENDPOINTS[0], headers=h).json == {"items": []}
    assert c.get(ENDPOINTS[1], headers=h).json == {"status": "not_subscribed", "subscription": None}
    assert c.get(ENDPOINTS[2], headers=h).json == {"status": "not_subscribed", "items": []}


def test_catalog_only_active_plans_and_prices(tenants):
    with tenants["client"].application.app_context():
        add_plan("basic")
        add_plan("hidden", active=False)
        basic = db.session.scalar(select(BillingPlan).where(BillingPlan.code == "basic"))
        db.session.add(BillingPlanPrice(plan_id=basic.id, currency="MXN", billing_interval="year", amount=Decimal("1990.00"), version=1, active=False))
        db.session.commit()
    r = tenants["client"].get(ENDPOINTS[0], headers=tenants["ha"])
    assert r.status_code == 200
    assert len(r.json["items"]) == 1
    item = r.json["items"][0]
    assert item["code"] == "basic"
    assert len(item["prices"]) == 1
    assert item["prices"][0]["amount"] == "199.00"
    assert {e["feature_code"] for e in item["entitlements"]} == {"members", "clients", "events", "custom_feature"}


def test_subscription_and_usage_isolated_by_tenant(tenants):
    c = tenants["client"]
    with c.application.app_context():
        _, price_a = add_plan("basic")
        _, price_b = add_plan("premium")
        sub_a = subscribe(tenants["a"], price_a)
        sub_b = subscribe(tenants["b"], price_b)
    ra = c.get(ENDPOINTS[1], headers=tenants["ha"])
    rb = c.get(ENDPOINTS[1], headers=tenants["hb"])
    assert ra.status_code == rb.status_code == 200
    assert ra.json["subscription"]["id"] == sub_a
    assert rb.json["subscription"]["id"] == sub_b
    assert ra.json["subscription"]["plan_code"] == "basic"
    assert rb.json["subscription"]["plan_code"] == "premium"
    for headers in (tenants["ha"], tenants["hb"]):
        usage = c.get(ENDPOINTS[2], headers=headers)
        assert usage.status_code == 200
        assert usage.json["status"] == "active"
        items = {x["feature_code"]: x for x in usage.json["items"]}
        assert items["members"]["used"] == 1
        assert items["members"]["remaining"] == 2
        assert items["clients"]["used"] == 0
        assert items["events"]["used"] == 0
        assert items["custom_feature"]["used"] is None
        assert items["custom_feature"]["remaining"] is None
    # A cannot select B's subscription by changing only the tenant header.
    stolen = {**tenants["ha"], "X-Tenant-ID": str(tenants["b"])}
    for endpoint in ENDPOINTS[1:]:
        assert c.get(endpoint, headers=stolen).status_code == 403
