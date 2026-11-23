"""BILL-01.3.1: safe, repeatable catalog bootstrap (no price rewriting)."""
from decimal import Decimal
from sqlalchemy import select
from app.extensions import db
from app.models.billing import BillingPlan, BillingPlanPrice, BillingPlanEntitlement

# Prices are MXN, before any tax policy has been established.
# None means unlimited; 0 means disabled.
CATALOG = (
    {"code": "basic", "name": "Básico", "description": "Operación esencial de eventos", "month": "299.00", "year": "2511.60",
     "features": {"members": 3, "clients": 100, "events": 30, "inventory": 1, "quotes_contracts": 1, "advanced_reports": 0, "external_api": 0}},
    {"code": "professional", "name": "Profesional", "description": "Operación de eventos en crecimiento", "month": "699.00", "year": "5871.60",
     "features": {"members": 10, "clients": 1000, "events": 300, "inventory": 1, "quotes_contracts": 1, "advanced_reports": 1, "external_api": 0}},
    {"code": "enterprise", "name": "Empresarial", "description": "Operación avanzada de eventos", "month": "1499.00", "year": "12591.60",
     "features": {"members": None, "clients": None, "events": None, "inventory": 1, "quotes_contracts": 1, "advanced_reports": 1, "external_api": 1}},
)


# Nivel gratuito: se aplica a empresas sin suscripción vigente. No tiene precios
# ni se ofrece en el catálogo. Límites editables en MySQL (billing_plan_entitlements).
FREE_PLAN_CODE = "free"
FREE_TIER = {"code": FREE_PLAN_CODE, "name": "Gratuito", "description": "Funciones básicas sin costo",
             "features": {"members": 1, "clients": 25, "events": 10, "inventory": 1, "quotes_contracts": 1,
                          "advanced_reports": 0, "external_api": 0}}


class CatalogConflict(RuntimeError):
    """Existing catalog differs from the approved seed; manual review needed."""


def seed_billing_catalog():
    """Insert missing records, verify existing ones, and commit atomically.

    Never edits an existing plan, entitlement, or price. On mismatch aborts
    instead of silently modifying a published catalog or historical prices.
    Run only as a controlled operator task, not at application startup.
    """
    created = {"plans": 0, "prices": 0, "entitlements": 0}
    try:
        for item in CATALOG:
            plan = db.session.scalar(select(BillingPlan).where(BillingPlan.code == item["code"]))
            if plan is None:
                plan = BillingPlan(code=item["code"], name=item["name"], description=item["description"], active=True)
                db.session.add(plan)
                db.session.flush()
                created["plans"] += 1
            elif plan.name != item["name"] or plan.description != item["description"] or not plan.active:
                raise CatalogConflict(f"Plan {item['code']} differs from approved catalog")

            for interval in ("month", "year"):
                amount = Decimal(item[interval])
                price = db.session.scalar(select(BillingPlanPrice).where(
                    BillingPlanPrice.plan_id == plan.id,
                    BillingPlanPrice.currency == "MXN",
                    BillingPlanPrice.billing_interval == interval,
                    BillingPlanPrice.version == 1,
                ))
                if price is None:
                    db.session.add(BillingPlanPrice(plan_id=plan.id, currency="MXN", billing_interval=interval,
                                                    amount=amount, version=1, active=True))
                    created["prices"] += 1
                elif Decimal(price.amount) != amount:
                    raise CatalogConflict(f"Price {item['code']}/{interval}/v1 differs from approved catalog")
                elif not price.active:
                    # v1 may be retired only by operator versioning (a newer version exists).
                    newer = db.session.scalar(select(BillingPlanPrice.id).where(
                        BillingPlanPrice.plan_id == plan.id,
                        BillingPlanPrice.currency == "MXN",
                        BillingPlanPrice.billing_interval == interval,
                        BillingPlanPrice.version > 1,
                    ).limit(1))
                    if newer is None:
                        raise CatalogConflict(f"Price {item['code']}/{interval}/v1 is inactive without a newer version")

            for code, limit in item["features"].items():
                entitlement = db.session.scalar(select(BillingPlanEntitlement).where(
                    BillingPlanEntitlement.plan_id == plan.id,
                    BillingPlanEntitlement.feature_code == code,
                ))
                if entitlement is None:
                    db.session.add(BillingPlanEntitlement(plan_id=plan.id, feature_code=code, limit_value=limit))
                    created["entitlements"] += 1
                elif entitlement.limit_value != limit:
                    raise CatalogConflict(f"Entitlement {item['code']}/{code} differs from approved catalog")
        db.session.commit()
        return created
    except Exception:
        db.session.rollback()
        raise


def seed_free_tier():
    """Insert the free tier if missing. Existing limits are never overwritten
    (operators may have tuned them in MySQL)."""
    created = {"plans": 0, "entitlements": 0}
    try:
        plan = db.session.scalar(select(BillingPlan).where(BillingPlan.code == FREE_PLAN_CODE))
        if plan is None:
            plan = BillingPlan(code=FREE_PLAN_CODE, name=FREE_TIER["name"],
                               description=FREE_TIER["description"], active=True)
            db.session.add(plan)
            db.session.flush()
            created["plans"] += 1
        for code, limit in FREE_TIER["features"].items():
            exists = db.session.scalar(select(BillingPlanEntitlement.id).where(
                BillingPlanEntitlement.plan_id == plan.id, BillingPlanEntitlement.feature_code == code))
            if exists is None:
                db.session.add(BillingPlanEntitlement(plan_id=plan.id, feature_code=code, limit_value=limit))
                created["entitlements"] += 1
        db.session.commit()
        return created
    except Exception:
        db.session.rollback()
        raise
