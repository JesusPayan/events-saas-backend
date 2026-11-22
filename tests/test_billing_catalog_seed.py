"""BILL-01.3.1 seed tests: isolated SQLite, no writes to MySQL."""
from decimal import Decimal
import pytest
from sqlalchemy import select, func
from app import create_app
from app.extensions import db
from app.models.billing import BillingPlan, BillingPlanPrice, BillingPlanEntitlement
from app.services.billing.catalog_seed import CATALOG, CatalogConflict, seed_billing_catalog
from app.services.billing.catalog_service import list_active_plans


@pytest.fixture
def catalog_app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "SECRET_KEY": "catalog-test-key", "JWT_SECRET_KEY": "catalog-test-jwt-key",
                      "CHECK_DB_ON_STARTUP": False})
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def count(model):
    return db.session.scalar(select(func.count()).select_from(model))


def test_seed_creates_three_plans_six_prices_and_entitlements(catalog_app):
    assert seed_billing_catalog() == {"plans": 3, "prices": 6, "entitlements": 21}
    assert count(BillingPlan) == 3
    assert count(BillingPlanPrice) == 6
    assert count(BillingPlanEntitlement) == 21


def test_seed_is_idempotent(catalog_app):
    seed_billing_catalog()
    assert seed_billing_catalog() == {"plans": 0, "prices": 0, "entitlements": 0}
    assert (count(BillingPlan), count(BillingPlanPrice), count(BillingPlanEntitlement)) == (3, 6, 21)


@pytest.mark.parametrize("code,monthly,annual", [
    ("basic", "299.00", "2511.60"),
    ("professional", "699.00", "5871.60"),
    ("enterprise", "1499.00", "12591.60"),
])
def test_approved_prices_and_annual_discount(catalog_app, code, monthly, annual):
    seed_billing_catalog()
    plan = db.session.scalar(select(BillingPlan).where(BillingPlan.code == code))
    prices = db.session.scalars(select(BillingPlanPrice).where(BillingPlanPrice.plan_id == plan.id)).all()
    values = {p.billing_interval: Decimal(p.amount) for p in prices}
    assert values == {"month": Decimal(monthly), "year": Decimal(annual)}
    assert values["year"] == values["month"] * 12 * Decimal("0.70")
    assert all(p.currency == "MXN" and p.version == 1 and p.active for p in prices)


def test_limits_and_unlimited(catalog_app):
    seed_billing_catalog()
    by_code = {p.code: p for p in db.session.scalars(select(BillingPlan)).all()}
    for item in CATALOG:
        limits = {e.feature_code: e.limit_value for e in db.session.scalars(select(BillingPlanEntitlement).where(
            BillingPlanEntitlement.plan_id == by_code[item["code"]].id)).all()}
        assert limits == item["features"]
    assert all(by_code.values())


def test_existing_price_conflict_rolls_back_without_overwrite(catalog_app):
    seed_billing_catalog()
    p = db.session.scalar(select(BillingPlanPrice).where(BillingPlanPrice.billing_interval == "month"))
    p.amount = Decimal("999.00")
    db.session.commit()
    with pytest.raises(CatalogConflict):
        seed_billing_catalog()
    db.session.expire_all()
    assert db.session.get(BillingPlanPrice, p.id).amount == Decimal("999.00")
    assert count(BillingPlanPrice) == 6


def test_existing_entitlement_conflict_rolls_back(catalog_app):
    seed_billing_catalog()
    e = db.session.scalar(select(BillingPlanEntitlement).where(BillingPlanEntitlement.feature_code == "members"))
    e.limit_value = 999
    db.session.commit()
    with pytest.raises(CatalogConflict):
        seed_billing_catalog()
    assert count(BillingPlanEntitlement) == 21


def test_catalog_read_service_exposes_seed(catalog_app):
    seed_billing_catalog()
    items = list_active_plans()
    assert len(items) == 3
    assert {p["code"] for p in items} == {"basic", "professional", "enterprise"}
    assert all(len(p["prices"]) == 2 and len(p["entitlements"]) == 7 for p in items)
