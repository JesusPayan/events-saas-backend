"""WEB-01: catálogo público para la landing (sin autenticación, sin datos internos)."""
from decimal import Decimal

from app.extensions import db
from app.models.billing import BillingPlan, BillingPlanPrice
from app.services.billing.catalog_seed import seed_billing_catalog, seed_free_tier
from tests.test_identity import client  # noqa: F401


def test_public_plans_without_auth_from_mysql(client):
    with client.application.app_context():
        seed_billing_catalog()
        seed_free_tier()
    r = client.get("/api/v1/public/plans")
    assert r.status_code == 200
    assert "max-age" in r.headers["Cache-Control"]
    data = r.json
    by_code = {p["code"]: p for p in data["plans"]}
    assert set(by_code) == {"basic", "professional", "enterprise"}
    assert {(p["billing_interval"], p["amount"]) for p in by_code["basic"]["prices"]} == {("month", "299.00"), ("year", "2511.60")}
    assert data["free_tier"]["code"] == "free" and data["free_tier"]["entitlements"]
    # Sin identificadores internos de precio ni versiones.
    assert all(set(p) == {"billing_interval", "amount", "currency"} for plan in data["plans"] for p in plan["prices"])


def test_public_plans_reflect_repricing_and_hide_inactive(client):
    with client.application.app_context():
        seed_billing_catalog()
        plan = db.session.query(BillingPlan).filter_by(code="basic").one()
        v1 = db.session.query(BillingPlanPrice).filter_by(plan_id=plan.id, billing_interval="month").one()
        v1.active = False
        db.session.add(BillingPlanPrice(plan_id=plan.id, currency="MXN", billing_interval="month",
                                        amount=Decimal("349.00"), version=2, active=True))
        enterprise = db.session.query(BillingPlan).filter_by(code="enterprise").one()
        enterprise.active = False
        db.session.commit()
    data = client.get("/api/v1/public/plans").json
    by_code = {p["code"]: p for p in data["plans"]}
    assert "enterprise" not in by_code
    assert ("month", "349.00") in {(p["billing_interval"], p["amount"]) for p in by_code["basic"]["prices"]}
    assert data["free_tier"] is None  # sin sembrar, no se anuncia
