"""MOD-01: giros comerciales, módulos, motor de capacidades y onboarding.

Usa la configuración real de módulos (marca ``mod01``): una organización nueva
arranca solo con los módulos comunes hasta completar el onboarding.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Tenant
from app.models.identity import now
from app.models.platform import AuditEvent
from app.modules_registry import ModuleDef, OPTIONAL_MODULES, find_cycle, validate_registry
from app.services.catalog_service import seed_categories
from tests.test_identity import client  # noqa: F401
from tests.test_roles_catalog import bootstrap_owner, login

pytestmark = pytest.mark.mod01
PASSWORD = "a-very-long-password"


def register(client, email, slug):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD, "slug": slug,
                                                    "company_name": f"Empresa {slug}"})
    assert r.status_code == 201, r.json
    return r.json["tenant_id"], {**login(client, email), "X-Tenant-ID": str(r.json["tenant_id"])}


@pytest.fixture
def ready(client):
    with client.application.app_context():
        from app.services.capability_service import seed_catalog
        seed_catalog()
        seed_categories()
    return client


def actions(client, tenant_id=None):
    with client.application.app_context():
        query = select(AuditEvent)
        if tenant_id is not None:
            query = query.where(AuditEvent.tenant_id == tenant_id)
        return [(a.action, a.details) for a in db.session.scalars(query).all()]


def caps(client, h):
    r = client.get("/api/v1/tenants/current/capabilities", headers=h)
    assert r.status_code == 200, r.json
    return r.json


def complete(client, h, types, modules=None):
    if modules is None:
        preview = client.post("/api/v1/onboarding/preview", json={"business_types": types}, headers=h).json
        modules = {m["code"]: m["state"] == "selected" for m in preview["modules"] if m["code"] in OPTIONAL_MODULES}
    return client.post("/api/v1/onboarding/complete", json={"business_types": types, "modules": modules}, headers=h)


# ----------------------------------------------------------------------------
# Registro y onboarding
# ----------------------------------------------------------------------------

def test_new_organization_starts_with_common_modules_and_pending_onboarding(ready):
    client = ready
    _, h = register(client, "nueva@example.test", "nueva-co")
    data = caps(client, h)
    assert data["onboarding"] == "pending"
    assert set(data["effective_modules"]) >= {"CORE_CLIENTS", "COMMERCIAL_QUOTES", "COMMERCIAL_CONTRACTS",
                                              "COMMERCIAL_CATALOG"}
    assert "INVENTORY" not in data["effective_modules"]
    status = client.get("/api/v1/onboarding/status", headers=h).json
    assert status["required"] is True and status["can_manage"] is True
    # Módulo no habilitado: escribir se bloquea; consultar no (política no destructiva).
    blocked = client.post("/api/v1/inventory/items", json={"sku": "X1", "name": "Silla"}, headers=h)
    assert blocked.status_code == 403 and blocked.json == {"error": "module_disabled", "module": "INVENTORY"}
    assert client.get("/api/v1/inventory/items", headers=h).status_code == 200


def test_business_type_catalog_and_selection_rules(ready):
    client = ready
    _, h = register(client, "giros@example.test", "giros-co")
    types = client.get("/api/v1/business-types", headers=h).json["items"]
    codes = {t["code"] for t in types}
    assert len(codes) == 18 and "LEGACY_COMPATIBILITY" not in codes
    furniture = next(t for t in types if t["code"] == "FURNITURE_RENTAL")
    assert {"INVENTORY", "LOGISTICS", "REPORTS"} <= set(furniture["recommended_modules"])

    def patch(items):
        return client.patch("/api/v1/tenants/current/business-types", json={"items": items}, headers=h)
    assert patch([{"code": "PHOTOGRAPHY"}]).json["error"] == "primary_business_type_required"
    assert patch([{"code": "PHOTOGRAPHY", "is_primary": True}, {"code": "VIDEOGRAPHY", "is_primary": True}]
                 ).json["error"] == "primary_business_type_required"
    assert patch([{"code": "LEGACY_COMPATIBILITY", "is_primary": True}]).json["error"] == "business_type_not_available"
    assert patch([{"code": "NOPE", "is_primary": True}]).json["error"] == "business_type_not_available"
    assert patch([{"code": "OTHER", "is_primary": True}]).json["error"] == "custom_description_required"
    ok = patch([{"code": "PHOTOGRAPHY", "is_primary": True}, {"code": "VIDEOGRAPHY"},
                {"code": "OTHER", "custom_description": "Cabina de fotos"}])
    assert ok.status_code == 200, ok.json
    current = client.get("/api/v1/tenants/current/business-types", headers=h).json["items"]
    assert [t["code"] for t in current if t["is_primary"]] == ["PHOTOGRAPHY"]
    assert next(t for t in current if t["code"] == "OTHER")["custom_description"] == "Cabina de fotos"
    # Cambiar de giro no cambia módulos (salvo que se pida aplicar recomendaciones).
    assert "INVENTORY" not in caps(client, h)["effective_modules"]


def test_preview_combines_multiple_business_types_and_resolves_dependencies(ready):
    client = ready
    _, h = register(client, "multi@example.test", "multi-co")
    preview = client.post("/api/v1/onboarding/preview", json={"business_types": [
        {"code": "PHOTOGRAPHY", "is_primary": True}, {"code": "FURNITURE_RENTAL"}]}, headers=h).json
    assert set(preview["recommended"]) >= {"INVENTORY", "LOGISTICS", "REPORTS", "ORGANIZATION_NETWORK",
                                           "COMMERCIAL_CATALOG"}
    states = {m["code"]: m["state"] for m in preview["modules"]}
    assert states["CORE_CLIENTS"] == "essential" and states["SPACE_BOOKING"] == "coming_soon"
    # Elegir LOGISTICS sin INVENTORY: la dependencia se agrega sola.
    custom = client.post("/api/v1/onboarding/preview", json={"business_types": [
        {"code": "DJ_SERVICE", "is_primary": True}], "modules": {"LOGISTICS": True}}, headers=h).json
    assert {m["code"] for m in custom["modules"] if m["state"] == "selected"} == {"LOGISTICS", "INVENTORY"}
    assert "/logistics" in [r for w in custom["workspace"] for r in w["routes"]]


def test_onboarding_draft_resume_and_idempotent_completion(ready):
    client = ready
    tenant, h = register(client, "onb@example.test", "onb-co")
    draft = {"business_types": [{"code": "FURNITURE_RENTAL", "is_primary": True}], "step": 3}
    r = client.put("/api/v1/onboarding/draft", json=draft, headers=h)
    assert r.status_code == 200 and r.json["status"] == "in_progress" and r.json["current_step"] == 3
    # Recuperar el progreso en otra sesión.
    again = client.get("/api/v1/onboarding/status", headers={**login(client, "onb@example.test"),
                                                             "X-Tenant-ID": str(tenant)}).json
    assert again["draft"]["business_types"][0]["code"] == "FURNITURE_RENTAL"

    first = complete(client, h, draft["business_types"])
    assert first.status_code == 200 and first.json["already_completed"] is False
    assert first.json["applied_templates"] == {"FURNITURE_RENTAL": 1}
    second = complete(client, h, [{"code": "DJ_SERVICE", "is_primary": True}], {"INVENTORY": False})
    assert second.status_code == 200 and second.json["already_completed"] is True
    data = caps(client, h)
    assert data["onboarding"] == "completed"
    assert {"INVENTORY", "LOGISTICS", "REPORTS"} <= set(data["effective_modules"])
    assert [t["code"] for t in data["business_types"]] == ["FURNITURE_RENTAL"]
    assert client.post("/api/v1/inventory/items", json={"sku": "S1", "name": "Silla"}, headers=h).status_code == 201
    names = [a for a, _ in actions(client, tenant)]
    assert {"onboarding.started", "business_profile.selected", "module.enabled", "onboarding.completed"} <= set(names)
    assert names.count("onboarding.completed") == 1
    assert client.put("/api/v1/onboarding/draft", json=draft, headers=h).json["error"] == "onboarding_completed"


def test_invited_member_does_not_repeat_onboarding_and_cannot_configure(ready):
    client = ready
    tenant, h = register(client, "owner-inv@example.test", "owner-inv")
    complete(client, h, [{"code": "CATERING", "is_primary": True}])
    from unittest.mock import patch
    with patch("app.api.members.send_email"):
        inv = client.post("/api/v1/invitations", json={"email": "staff-inv@example.test", "role": "staff"}, headers=h)
    client.post("/api/v1/invitations/accept", json={"token": inv.json["invite_url"].split("#token=")[1],
                                                    "password": PASSWORD})
    hs = {**login(client, "staff-inv@example.test"), "X-Tenant-ID": str(tenant)}
    status = client.get("/api/v1/onboarding/status", headers=hs).json
    assert status["required"] is False and status["can_manage"] is False
    assert client.patch("/api/v1/tenants/current/modules", json={"modules": {"REPORTS": True}},
                        headers=hs).status_code == 403
    assert client.post("/api/v1/onboarding/complete", json={"business_types": [], "modules": {}},
                       headers=hs).status_code == 403
    assert "INVENTORY" in caps(client, hs)["effective_modules"]


# ----------------------------------------------------------------------------
# Motor de capacidades: dependencias, códigos desconocidos y desactivación segura
# ----------------------------------------------------------------------------

def test_registry_rejects_circular_and_unknown_dependencies():
    a = ModuleDef("A", "A", "", "x", "c", 1, depends_on=("B",))
    b = ModuleDef("B", "B", "", "x", "c", 2, depends_on=("C",))
    c = ModuleDef("C", "C", "", "x", "c", 3, depends_on=("A",))
    assert find_cycle((a, b, c)) is not None
    with pytest.raises(ValueError, match="circular"):
        validate_registry((a, b, c))
    with pytest.raises(ValueError, match="inexistentes"):
        validate_registry((ModuleDef("X", "X", "", "x", "c", 1, depends_on=("Y",)),))
    validate_registry()  # el registro real es válido


def test_dependencies_unknown_codes_essentials_and_future_modules(ready):
    client = ready
    tenant, h = register(client, "deps@example.test", "deps-co")

    def patch(modules):
        return client.patch("/api/v1/tenants/current/modules", json={"modules": modules}, headers=h)
    r = patch({"LOGISTICS": True})
    assert r.status_code == 200 and r.json["result"]["auto_enabled"] == ["INVENTORY"]
    assert {"LOGISTICS", "INVENTORY"} <= set(caps(client, h)["effective_modules"])
    blocked = patch({"INVENTORY": False})
    assert blocked.status_code == 409 and blocked.json["error"] == "module_dependency_required"
    assert blocked.json["dependents"] == ["LOGISTICS"]
    assert patch({"INVENTORY": False, "LOGISTICS": False}).status_code == 200
    assert patch({"HACKED_MODULE": True}).json["error"] == "unknown_module"
    assert patch({"CORE_CLIENTS": False}).json["error"] == "module_essential"
    assert patch({"SPACE_BOOKING": True}).json["error"] == "module_unavailable"
    assert patch({"INVENTORY": "yes"}).json["error"] == "invalid_modules"
    # Capacidades desconocidas nunca conceden acceso.
    with client.application.test_request_context():
        from app.services.capability_service import can_use_capability
        assert can_use_capability(tenant, "inventory.items") is False
        assert can_use_capability(tenant, "made.up") is False
    assert any(a == "module.dependency_resolved" for a, _ in actions(client, tenant))


def test_safe_disable_keeps_history_and_reactivation_restores_access(ready):
    client = ready
    tenant, h = register(client, "safe@example.test", "safe-co")
    complete(client, h, [{"code": "FURNITURE_RENTAL", "is_primary": True}])
    item = client.post("/api/v1/inventory/items", json={"sku": "M1", "name": "Mesa", "quantity_total": 10},
                       headers=h).json["id"]
    c = client.post("/api/v1/clients", json={"first_name": "Ana", "last_name": "Ruiz"}, headers=h).json["id"]
    start = (now() + timedelta(days=10)).strftime("%Y-%m-%dT18:00:00Z")
    end = (now() + timedelta(days=10)).strftime("%Y-%m-%dT23:00:00Z")
    e = client.post("/api/v1/events", json={"client_id": c, "event_type": "social", "name": "Evento",
                                            "starts_at": start, "ends_at": end}, headers=h).json["id"]
    res = client.post(f"/api/v1/events/{e}/reservations", json={"inventory_item_id": item, "quantity": 4}, headers=h)
    assert res.status_code == 201, res.json

    def patch(modules):
        return client.patch("/api/v1/tenants/current/modules", json={"modules": modules}, headers=h)
    rejected = patch({"INVENTORY": False, "LOGISTICS": False, "REPORTS": False})
    assert rejected.status_code == 409 and rejected.json["error"] == "module_has_active_operations"
    assert rejected.json["modules"]["INVENTORY"][0]["type"] == "inventory_reservations"
    impact = client.get("/api/v1/tenants/current/modules/INVENTORY/impact", headers=h).json
    assert impact["operations"][0]["count"] == 1 and set(impact["dependents"]) >= {"LOGISTICS", "REPORTS"}
    assert "module.disable_rejected" in [a for a, _ in actions(client, tenant)]
    # Al cancelar la reserva, se puede desactivar; los datos se conservan y se pueden consultar.
    reservation_id = res.json["id"]
    assert client.patch(f"/api/v1/events/{e}/reservations/{reservation_id}/cancel", json={},
                       headers=h).status_code == 200
    assert patch({"INVENTORY": False, "LOGISTICS": False, "REPORTS": False}).status_code == 200
    assert client.get(f"/api/v1/inventory/items/{item}", headers=h).status_code == 200
    assert client.patch(f"/api/v1/inventory/items/{item}", json={"name": "Mesa 2"}, headers=h).status_code == 403
    # Reactivar recupera el acceso a los mismos datos.
    assert patch({"INVENTORY": True}).status_code == 200
    assert client.patch(f"/api/v1/inventory/items/{item}", json={"name": "Mesa 2"}, headers=h).status_code == 200
    # Una cotización no puede usar inventario si el módulo está apagado.
    patch({"INVENTORY": False})
    q = client.post("/api/v1/quotes", json={"client_id": c, "event_id": e, "items": [
        {"item_type": "inventory", "inventory_item_id": item, "description": "Mesa", "quantity": "1",
         "unit_price": "10.00"}]}, headers=h)
    assert q.status_code == 403 and q.json["details"]["module"] == "INVENTORY"


# ----------------------------------------------------------------------------
# Suscripciones: el giro no otorga funciones de pago
# ----------------------------------------------------------------------------

def test_plan_entitlements_upgrade_downgrade_and_no_paid_access_from_business_type(ready):
    client = ready
    app = client.application
    tenant, h = register(client, "plan@example.test", "plan-co")
    register(client, "root-plan@example.test", "root-plan")
    with app.app_context():
        from app.services.billing.catalog_seed import seed_billing_catalog, seed_free_tier
        seed_billing_catalog()
        seed_free_tier()
        bootstrap_owner("root-plan@example.test")
    h_root = login(client, "root-plan@example.test")
    plans = {p["code"]: p["id"] for p in client.get("/api/v1/platform/plans", headers=h_root).json["items"]}
    # Solo el dueño configura planes; el plan gratuito incluye solo el catálogo.
    r = client.put(f"/api/v1/platform/plans/{plans['free']}/modules", json={"modules": ["COMMERCIAL_CATALOG"]},
                   headers=h_root)
    assert r.status_code == 200 and r.json["restricted"] is True
    assert client.put(f"/api/v1/platform/plans/{plans['free']}/modules", json={"modules": ["FAKE"]},
                      headers=h_root).json["error"] == "unknown_module"
    app.config["BILLING_ENFORCE_ENTITLEMENTS"] = True
    try:
        data = caps(client, h)
        assert data["plan_restricted"] is True
        statuses = {m["code"]: m["status"] for m in data["modules"]}
        assert statuses["COMMERCIAL_CONTRACTS"] == "plan_locked" and statuses["COMMERCIAL_CATALOG"] == "active"
        assert client.post("/api/v1/contracts", json={}, headers=h).json["error"] == "plan_upgrade_required"
        assert client.get("/api/v1/contracts", headers=h).status_code == 200  # consultar sigue permitido
        # Elegir un giro con inventario no lo habilita gratis.
        assert client.patch("/api/v1/tenants/current/modules", json={"modules": {"INVENTORY": True}},
                            headers=h).json["error"] == "plan_upgrade_required"
        r = client.patch("/api/v1/tenants/current/business-types", json={
            "items": [{"code": "FURNITURE_RENTAL", "is_primary": True}], "apply_recommendations": True}, headers=h)
        assert r.status_code == 200 and "INVENTORY" not in r.json["result"]["enabled_modules"]
        preview = client.post("/api/v1/onboarding/preview", json={"business_types": [
            {"code": "FURNITURE_RENTAL", "is_primary": True}]}, headers=h).json
        assert {m["code"]: m["state"] for m in preview["modules"]}["INVENTORY"] == "requires_upgrade"
        # Upgrade: suscripción vigente a un plan sin restricciones de módulos.
        with app.app_context():
            from app.models.billing import BillingPlan, BillingPlanPrice, TenantSubscription
            plan = db.session.scalar(select(BillingPlan).where(BillingPlan.code == "professional"))
            price = db.session.scalar(select(BillingPlanPrice).where(BillingPlanPrice.plan_id == plan.id))
            sub = TenantSubscription(tenant_id=tenant, plan_price_id=price.id, status="active",
                                     current_period_start=now() - timedelta(days=1),
                                     current_period_end=now() + timedelta(days=29), provider="mercadopago")
            db.session.add(sub)
            db.session.commit()
            sub_id, price_id = sub.id, price.id
        assert caps(client, h)["plan_restricted"] is False
        assert client.patch("/api/v1/tenants/current/modules", json={"modules": {"INVENTORY": True}},
                            headers=h).status_code == 200
        item = client.post("/api/v1/inventory/items", json={"sku": "P1", "name": "Silla"}, headers=h)
        assert item.status_code == 201
        # Cancelada: conserva el acceso hasta el fin del periodo pagado (regla existente).
        with app.app_context():
            sub = db.session.get(TenantSubscription, sub_id)
            sub.status, sub.canceled_at = "canceled", now()
            db.session.commit()
        assert "INVENTORY" in caps(client, h)["effective_modules"]
        # Vencida: downgrade no destructivo (datos consultables, escritura bloqueada).
        with app.app_context():
            sub = db.session.get(TenantSubscription, sub_id)
            sub.current_period_end = now() - timedelta(minutes=1)
            db.session.commit()
        assert client.get(f"/api/v1/inventory/items/{item.json['id']}", headers=h).status_code == 200
        assert client.post("/api/v1/inventory/items", json={"sku": "P2", "name": "Mesa"},
                           headers=h).json["error"] == "plan_upgrade_required"
        # Reactivación: nueva suscripción vigente devuelve el acceso con los mismos datos.
        with app.app_context():
            db.session.add(TenantSubscription(tenant_id=tenant, plan_price_id=price_id, status="active",
                                              current_period_start=now() - timedelta(minutes=1),
                                              current_period_end=now() + timedelta(days=30), provider="mercadopago"))
            db.session.commit()
        assert client.post("/api/v1/inventory/items", json={"sku": "P2", "name": "Mesa"}, headers=h).status_code == 201
    finally:
        app.config["BILLING_ENFORCE_ENTITLEMENTS"] = False
    assert "plan.entitlements_updated" in [a for a, _ in actions(client)]


def test_existing_plan_conditions_are_preserved_without_configuration(ready):
    """Sin módulos configurados en el plan, nada cambia respecto a v1.2.0."""
    client = ready
    app = client.application
    _, h = register(client, "keep@example.test", "keep-co")
    with app.app_context():
        from app.services.billing.catalog_seed import seed_free_tier
        seed_free_tier()
    app.config["BILLING_ENFORCE_ENTITLEMENTS"] = True
    try:
        assert caps(client, h)["plan_restricted"] is False
    finally:
        app.config["BILLING_ENFORCE_ENTITLEMENTS"] = False


# ----------------------------------------------------------------------------
# Aislamiento, roles de plataforma y compatibilidad
# ----------------------------------------------------------------------------

def test_tenant_isolation_and_identifier_manipulation(ready):
    client = ready
    tenant_a, h_a = register(client, "iso-a@example.test", "iso-a")
    tenant_b, h_b = register(client, "iso-b@example.test", "iso-b")
    complete(client, h_b, [{"code": "FLORIST", "is_primary": True}])
    forged = {**h_a, "X-Tenant-ID": str(tenant_b)}
    for method, path, body in (("get", "/api/v1/tenants/current/modules", None),
                               ("patch", "/api/v1/tenants/current/modules", {"modules": {"INVENTORY": False}}),
                               ("get", "/api/v1/tenants/current/business-types", None),
                               ("patch", "/api/v1/tenants/current/business-types",
                                {"items": [{"code": "DJ_SERVICE", "is_primary": True}]}),
                               ("get", "/api/v1/tenants/current/capabilities", None),
                               ("post", "/api/v1/onboarding/complete", {"business_types": [], "modules": {}}),
                               ("get", "/api/v1/tenants/current/modules/INVENTORY/impact", None)):
        r = getattr(client, method)(path, json=body, headers=forged)
        assert r.status_code == 403, (method, path)
    # No hay forma de indicar otro tenant en el cuerpo: los campos extra se rechazan.
    r = client.patch("/api/v1/tenants/current/modules", json={"modules": {"INVENTORY": True},
                                                              "tenant_id": tenant_b}, headers=h_a)
    assert r.status_code == 422
    assert "INVENTORY" in caps(client, h_b)["effective_modules"]
    assert "INVENTORY" not in caps(client, h_a)["effective_modules"]


def test_platform_catalog_templates_and_role_boundaries(ready):
    client = ready
    tenant, h = register(client, "tmpl@example.test", "tmpl-co")
    complete(client, h, [{"code": "PHOTOGRAPHY", "is_primary": True}])
    before = set(caps(client, h)["effective_modules"])
    register(client, "root-t@example.test", "root-t")
    register(client, "admin-t@example.test", "admin-t")
    register(client, "promo-t@example.test", "promo-t")
    with client.application.app_context():
        bootstrap_owner("root-t@example.test")
    h_root = login(client, "root-t@example.test")
    client.post("/api/v1/platform/roles", json={"email": "admin-t@example.test", "role": "platform_admin"},
                headers=h_root)
    client.post("/api/v1/platform/roles", json={"email": "promo-t@example.test", "role": "promoter"}, headers=h_root)
    h_admin, h_promo = login(client, "admin-t@example.test"), login(client, "promo-t@example.test")
    # Promotores y organizaciones no administran catálogos ni ven estadísticas.
    for hh in (h_promo, h):
        assert client.get("/api/v1/platform/business-types", headers=hh).status_code == 403
        assert client.get("/api/v1/platform/modules/adoption", headers=hh).status_code == 403
    types = client.get("/api/v1/platform/business-types", headers=h_admin).json["items"]
    photo = next(t for t in types if t["code"] == "PHOTOGRAPHY")
    assert photo["organizations"] == 1
    r = client.put(f"/api/v1/platform/business-types/{photo['id']}/modules",
                   json={"modules": ["LOGISTICS", "COMMERCIAL_CATALOG"]}, headers=h_admin)
    assert r.status_code == 200 and r.json["template_version"] == 2
    assert set(r.json["modules"]) == {"LOGISTICS", "INVENTORY", "COMMERCIAL_CATALOG"}
    # Cambiar la plantilla no altera organizaciones existentes.
    assert set(caps(client, h)["effective_modules"]) == before
    new = client.post("/api/v1/platform/business-types", json={"code": "PHOTO_BOOTH", "name": "Cabinas de fotos"},
                      headers=h_admin)
    assert new.status_code == 201
    assert client.post("/api/v1/platform/business-types", json={"code": "PHOTO_BOOTH", "name": "x"},
                       headers=h_admin).json["error"] == "code_taken"
    assert client.patch(f"/api/v1/platform/business-types/{new.json['item']['id']}", json={"is_active": False},
                        headers=h_admin).status_code == 200
    assert "PHOTO_BOOTH" not in {t["code"] for t in client.get("/api/v1/business-types", headers=h).json["items"]}
    # Planes y flags: solo el dueño.
    assert client.get("/api/v1/platform/plans", headers=h_admin).status_code == 403
    assert client.patch("/api/v1/platform/feature-flags/modules.enforcement", json={"enabled": False},
                        headers=h_admin).status_code == 403
    # Interruptor global de un módulo: esenciales no se pueden apagar.
    assert client.patch("/api/v1/platform/modules/CORE_CLIENTS", json={"is_active": False},
                        headers=h_admin).json["error"] == "module_essential"
    assert client.patch("/api/v1/platform/modules/ORGANIZATION_NETWORK", json={"is_active": False},
                        headers=h_admin).status_code == 200
    statuses = {m["code"]: m["status"] for m in caps(client, h)["modules"]}
    assert statuses["ORGANIZATION_NETWORK"] == "unavailable"
    stats = client.get("/api/v1/platform/modules/adoption", headers=h_admin).json
    assert stats["onboarding"]["completed"] == 1 and stats["primary_business_type"][0]["code"] == "PHOTOGRAPHY"
    assert {"module_template.updated", "business_type.create", "module.global_state"} <= {a for a, _ in actions(client)}


def test_feature_flag_controls_server_enforcement(ready):
    client = ready
    _, h = register(client, "flag@example.test", "flag-co")
    register(client, "root-f@example.test", "root-f")
    with client.application.app_context():
        bootstrap_owner("root-f@example.test")
    h_root = login(client, "root-f@example.test")
    assert client.post("/api/v1/inventory/items", json={"sku": "F1", "name": "Silla"}, headers=h).status_code == 403
    assert client.patch("/api/v1/platform/feature-flags/modules.enforcement", json={"enabled": False},
                        headers=h_root).status_code == 200
    assert client.post("/api/v1/inventory/items", json={"sku": "F1", "name": "Silla"}, headers=h).status_code == 201
    client.patch("/api/v1/platform/feature-flags/modules.enforcement", json={"enabled": True}, headers=h_root)
    assert client.post("/api/v1/inventory/items", json={"sku": "F2", "name": "Silla"}, headers=h).status_code == 403


def test_legacy_organization_keeps_all_previous_modules(ready):
    client = ready
    _, h = register(client, "legacy@example.test", "legacy-co")
    with client.application.app_context():
        # Organización creada antes de v1.3.0 (sin configuración de módulos).
        tenant = Tenant(name="Antigua SA", slug="antigua-sa", status="active")
        db.session.add(tenant)
        db.session.commit()
        legacy_id = tenant.id
        from app.services.capability_service import effective_modules, get_tenant_modules
        with client.application.test_request_context():
            assert set(OPTIONAL_MODULES) <= effective_modules(legacy_id)
            assert all(m["status"] in ("active", "unavailable") for m in get_tenant_modules(legacy_id))


def test_network_respects_disabled_module_and_business_type_filter(ready):
    client = ready
    _, h_a = register(client, "net-a@example.test", "net-a")
    _, h_b = register(client, "net-b@example.test", "net-b")
    complete(client, h_a, [{"code": "DJ_SERVICE", "is_primary": True}])
    complete(client, h_b, [{"code": "EVENT_PLANNER", "is_primary": True}])
    cats = {c["slug"]: c["id"] for c in client.get("/api/v1/catalog/categories", headers=h_a).json["items"]}
    r = client.post("/api/v1/catalog/offers", json={
        "name": "DJ 5 horas", "category_id": cats["dj-y-musica-grabada"], "pricing_mode": "per_event",
        "unit_price": "9000.00", "fulfillment_type": "manual", "status": "published", "shared": True}, headers=h_a)
    assert r.status_code == 201
    items = client.get("/api/v1/catalog/network", headers=h_b).json["items"]
    assert items[0]["supplier_business_types"] == ["DJ y entretenimiento"]
    assert len(client.get("/api/v1/catalog/network?business_type=DJ_SERVICE", headers=h_b).json["items"]) == 1
    assert client.get("/api/v1/catalog/network?business_type=FLORIST", headers=h_b).json["items"] == []
    assert client.get("/api/v1/catalog/network?business_type=x;drop", headers=h_b).status_code == 422
    # Si la organización apaga la red, sus ofertas dejan de verse.
    assert client.patch("/api/v1/tenants/current/modules", json={"modules": {"ORGANIZATION_NETWORK": False}},
                        headers=h_a).status_code == 200
    assert client.get("/api/v1/catalog/network", headers=h_b).json["items"] == []


def test_delegated_access_reads_capabilities_but_cannot_configure(ready):
    client = ready
    tenant, h = register(client, "dlg@example.test", "dlg-co")
    register(client, "root-d@example.test", "root-d")
    with client.application.app_context():
        bootstrap_owner("root-d@example.test")
    assert client.post("/api/v1/access-grants", json={"email": "root-d@example.test", "purpose": "support",
                                                      "days": 1}, headers=h).status_code == 201
    hd = {**login(client, "root-d@example.test"), "X-Tenant-ID": str(tenant)}
    assert client.get("/api/v1/tenants/current/capabilities", headers=hd).status_code == 200
    assert client.patch("/api/v1/tenants/current/modules", json={"modules": {"REPORTS": True}},
                        headers=hd).status_code == 403
    audit = [d for a, d in actions(client, tenant) if a == "delegated_access.use"]
    assert audit and audit[-1]["correlation_id"]
