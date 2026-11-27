"""MOD-01: motor centralizado de capacidades (CapabilityService).

Regla de acceso (se evalúa en el servidor en cada operación protegida):

    organización activa AND membresía o acceso delegado vigente AND permiso del rol
    AND módulo activo para la organización AND módulo incluido en el plan
    AND dependencias activas AND feature flag habilitado

- Lecturas: se permiten aunque el módulo esté deshabilitado o fuera del plan, para
  conservar el acceso a datos históricos (política no destructiva).
- Escrituras: exigen el módulo activo; si no, ``module_disabled``,
  ``plan_upgrade_required`` o ``module_unavailable``.
- Códigos desconocidos nunca conceden acceso.
- Caché por petición (``flask.g``): no hay caché entre peticiones, así que los
  cambios de plan, suscripción, permisos o módulos aplican de inmediato.
"""
from datetime import datetime, timezone

from flask import current_app, has_request_context
from sqlalchemy import func, select

from app.business_profiles_data import BUSINESS_TYPES, FEATURE_FLAGS, LEGACY_CODE, LEGACY_MODULES
from app.extensions import db
from app.models import Tenant
from app.models.identity import now
from app.models.modules import (
    BusinessType, BusinessTypeModule, FeatureFlag, Module, PlanModule, TenantBusinessType, TenantModule,
    TenantOnboarding,
)
from app.modules_registry import (
    AVAILABLE, CAPABILITY_MODULE, COMING_SOON, DEFAULT_NEW_TENANT_MODULES, ESSENTIAL_MODULES, MODULES,
    MODULES_BY_CODE, OPTIONAL_MODULES, dependency_closure, dependents_of,
)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class CapabilityError(Exception):
    def __init__(self, code, status=400, **extra):
        super().__init__(code)
        self.code, self.status, self.extra = code, status, extra


def _audit(actor_id, action, tenant_id=None, target_type=None, target_id=None, details=None):
    from app.services.platform_service import record_audit
    record_audit(actor_id, action, tenant_id=tenant_id, target_type=target_type, target_id=target_id,
                 details=details)


# ----------------------------------------------------------------------------
# Siembra idempotente (catálogo global)
# ----------------------------------------------------------------------------

def seed_catalog():
    """Sincroniza módulos con el registro, crea giros/plantillas y flags faltantes.

    No sobrescribe decisiones administrativas: estado global de módulos, giros
    editados ni plantillas ya existentes.
    """
    existing = {m.code: m for m in db.session.scalars(select(Module)).all()}
    for m in MODULES:
        row = existing.get(m.code)
        if row is None:
            db.session.add(Module(code=m.code, name=m.name, description=m.description, icon=m.icon,
                                  category=m.category, sort_order=m.sort_order, is_active=True))
        else:
            row.icon, row.category = m.icon, m.category
    db.session.flush()
    for code, name, description, icon, order, modules, custom in BUSINESS_TYPES:
        if db.session.scalar(select(BusinessType.id).where(BusinessType.code == code)) is None:
            bt = BusinessType(code=code, name=name, description=description, icon=icon, sort_order=order,
                              is_active=True, is_internal=False, allows_custom_description=custom,
                              template_version=1)
            db.session.add(bt)
            db.session.flush()
            for module_code in modules:
                db.session.add(BusinessTypeModule(business_type_id=bt.id, module_code=module_code))
    if db.session.scalar(select(BusinessType.id).where(BusinessType.code == LEGACY_CODE)) is None:
        legacy = BusinessType(code=LEGACY_CODE, name="Compatibilidad (organizaciones anteriores a v1.3.0)",
                              description="Perfil interno: conserva los módulos previos.", icon="shield",
                              sort_order=9999, is_active=True, is_internal=True, template_version=1)
        db.session.add(legacy)
        db.session.flush()
        for module_code in LEGACY_MODULES:
            db.session.add(BusinessTypeModule(business_type_id=legacy.id, module_code=module_code))
    for code, enabled, description in FEATURE_FLAGS:
        if db.session.get(FeatureFlag, code) is None:
            db.session.add(FeatureFlag(code=code, enabled=enabled, description=description))
    db.session.commit()


# ----------------------------------------------------------------------------
# Evaluación (con caché por petición)
# ----------------------------------------------------------------------------

def _cache():
    """Caché ligada a la petición HTTP actual (nunca se comparte entre peticiones)."""
    if not has_request_context():
        return {}
    from flask import request
    return request.environ.setdefault("easiacc.capability_cache", {})


def invalidate(tenant_id=None):
    cache = _cache()
    if tenant_id is None:
        cache.clear()
    else:
        cache.pop(("tenant", tenant_id), None)
    cache.pop("flags", None)
    cache.pop("global", None)


def flag_enabled(code):
    cache = _cache()
    if "flags" not in cache:
        cache["flags"] = {f.code: f.enabled for f in db.session.scalars(select(FeatureFlag)).all()}
    flags = cache["flags"]
    if code in flags:
        return flags[code]
    # Flags no sembrados: valor por defecto del código (seguro para el servidor).
    return dict((c, e) for c, e, _ in FEATURE_FLAGS).get(code, False)


def _globally_inactive():
    cache = _cache()
    if "global" not in cache:
        cache["global"] = set(db.session.scalars(select(Module.code).where(Module.is_active.is_(False))).all())
    return cache["global"]


def plan_allowed_modules(tenant_id):
    """Módulos que permite el plan vigente, o ``None`` si el plan no restringe.

    Solo aplica con BILLING_ENFORCE_ENTITLEMENTS (igual que los límites existentes).
    Sin plan vigente ni nivel gratuito sembrado: solo módulos esenciales (fail-closed).
    """
    if not current_app.config.get("BILLING_ENFORCE_ENTITLEMENTS", False):
        return None, None
    from app.services.billing.entitlements_service import effective_plan
    plan_id, tier, _reason = effective_plan(tenant_id)
    if plan_id is None:
        return set(), None
    rows = set(db.session.scalars(select(PlanModule.module_code).where(PlanModule.plan_id == plan_id)).all())
    return (rows or None), plan_id


def _snapshot(tenant_id):
    cache = _cache()
    key = ("tenant", tenant_id)
    if key in cache:
        return cache[key]
    onboarding = db.session.get(TenantOnboarding, tenant_id)
    configured = dict(db.session.execute(select(TenantModule.module_code, TenantModule.state).where(
        TenantModule.tenant_id == tenant_id)).all())
    if onboarding is None and not configured:
        # Organización anterior a v1.3.0 sin migrar: conserva todo lo que tenía.
        configured = {code: "enabled" for code in LEGACY_MODULES}
    plan_allowed, plan_id = plan_allowed_modules(tenant_id)
    inactive = _globally_inactive()
    statuses = {}
    for m in MODULES:
        if m.status == COMING_SOON or (m.feature_flag and not flag_enabled(m.feature_flag)):
            statuses[m.code] = "unavailable"
        elif m.code in inactive:
            statuses[m.code] = "unavailable"
        elif m.essential:
            statuses[m.code] = "active"
        elif configured.get(m.code) != "enabled":
            statuses[m.code] = "disabled"
        elif plan_allowed is not None and m.code not in plan_allowed:
            statuses[m.code] = "plan_locked"
        else:
            statuses[m.code] = "active"
    # Un módulo solo está activo si todas sus dependencias lo están.
    changed = True
    while changed:
        changed = False
        for m in MODULES:
            if statuses[m.code] == "active" and any(statuses[d] != "active" for d in m.depends_on):
                statuses[m.code] = "dependency_missing"
                changed = True
    snap = {
        "statuses": statuses, "configured": configured, "plan_allowed": plan_allowed, "plan_id": plan_id,
        "onboarding": onboarding.status if onboarding else "legacy",
    }
    cache[key] = snap
    return snap


def get_tenant_modules(tenant_id):
    snap = _snapshot(tenant_id)
    result = []
    for m in MODULES:
        result.append({
            "code": m.code, "name": m.name, "description": m.description, "icon": m.icon,
            "category": m.category, "sort_order": m.sort_order, "essential": m.essential,
            "configurable": m.configurable, "status": snap["statuses"][m.code],
            "enabled": snap["configured"].get(m.code) == "enabled" or m.essential,
            "in_plan": snap["plan_allowed"] is None or m.essential or m.code in snap["plan_allowed"],
            "depends_on": list(m.depends_on), "capabilities": list(m.capabilities),
            "availability": m.status, "routes": list(m.routes),
        })
    return result


def effective_modules(tenant_id):
    return {code for code, status in _snapshot(tenant_id)["statuses"].items() if status == "active"}


def get_effective_capabilities(tenant_id):
    active = effective_modules(tenant_id)
    return sorted(cap for cap, module in CAPABILITY_MODULE.items() if module in active)


def can_use_capability(tenant_id, capability):
    module = CAPABILITY_MODULE.get(capability)
    return module is not None and module in effective_modules(tenant_id)


def can_access_module(tenant_id, module_code, *, write):
    """Devuelve ``None`` si se permite o el código de error de negocio."""
    module = MODULES_BY_CODE.get(module_code)
    if module is None:
        return "module_unavailable"
    if not flag_enabled("modules.enforcement"):
        return None
    status = _snapshot(tenant_id)["statuses"][module_code]
    if status == "active" or not write:
        return None
    return {"disabled": "module_disabled", "plan_locked": "plan_upgrade_required",
            "dependency_missing": "module_dependency_required"}.get(status, "module_unavailable")


def get_recommended_modules(business_type_codes):
    rows = db.session.execute(select(BusinessTypeModule.module_code).join(
        BusinessType, BusinessType.id == BusinessTypeModule.business_type_id).where(
        BusinessType.code.in_(list(business_type_codes) or ["__none__"]), BusinessType.is_active.is_(True))).all()
    recommended = {code for (code,) in rows if code in OPTIONAL_MODULES}
    return resolve_module_dependencies(recommended)


def resolve_module_dependencies(codes):
    codes = {c for c in codes if c in MODULES_BY_CODE}
    return {c for c in dependency_closure(codes) if c in OPTIONAL_MODULES}


# ----------------------------------------------------------------------------
# Operaciones activas (desactivación segura)
# ----------------------------------------------------------------------------

def active_operations(tenant_id, module_code):
    """Operaciones vigentes que impiden desactivar el módulo (nunca se borra nada)."""
    from app.models.event import Event
    from app.models.quote import Quote
    from app.models.quote_item import QuoteItem
    found = []
    current = now()
    open_quotes = ("draft", "sent")
    if module_code == "INVENTORY":
        from app.models.inventory_reservation import InventoryReservation
        count = db.session.scalar(select(func.count(InventoryReservation.id)).join(
            Event, (Event.id == InventoryReservation.event_id) & (Event.tenant_id == InventoryReservation.tenant_id))
            .where(InventoryReservation.tenant_id == tenant_id, InventoryReservation.status == "reserved",
                   Event.status != "cancelled", Event.ends_at >= current)) or 0
        if count:
            found.append({"type": "inventory_reservations", "count": count,
                          "message": "Reservas de inventario para eventos vigentes."})
    elif module_code == "LOGISTICS":
        from app.models.logistics_order import LogisticsOrder
        count = db.session.scalar(select(func.count(LogisticsOrder.id)).where(
            LogisticsOrder.tenant_id == tenant_id,
            LogisticsOrder.status.notin_(("delivered", "cancelled", "returned", "completed")))) or 0
        if count:
            found.append({"type": "logistics_orders", "count": count,
                          "message": "Órdenes logísticas sin entregar o cancelar."})
    elif module_code in ("COMMERCIAL_CONTRACTS", "COMMERCIAL_PAYMENTS"):
        from app.models.contract import Contract
        count = db.session.scalar(select(func.count(Contract.id)).where(
            Contract.tenant_id == tenant_id, Contract.status.in_(("draft", "active")))) or 0
        if count:
            found.append({"type": "open_contracts", "count": count,
                          "message": "Contratos en borrador o activos."})
    elif module_code == "SUPPLIERS":
        count = db.session.scalar(select(func.count(QuoteItem.id)).join(
            Quote, (Quote.id == QuoteItem.quote_id) & (Quote.tenant_id == QuoteItem.tenant_id)).where(
            QuoteItem.tenant_id == tenant_id, QuoteItem.provider_id.is_not(None),
            Quote.status.in_(open_quotes))) or 0
        if count:
            found.append({"type": "supplier_items", "count": count,
                          "message": "Partidas de proveedores en cotizaciones abiertas."})
    elif module_code == "ORGANIZATION_NETWORK":
        count = db.session.scalar(select(func.count(QuoteItem.id)).join(
            Quote, (Quote.id == QuoteItem.quote_id) & (Quote.tenant_id == QuoteItem.tenant_id)).where(
            ((QuoteItem.tenant_id == tenant_id) | (QuoteItem.supplier_tenant_id == tenant_id)),
            QuoteItem.supplier_tenant_id.is_not(None), Quote.status.in_(open_quotes))) or 0
        if count:
            found.append({"type": "network_requests", "count": count,
                          "message": "Solicitudes entre organizaciones sin resolver."})
    elif module_code == "COMMERCIAL_CATALOG":
        count = db.session.scalar(select(func.count(QuoteItem.id)).join(
            Quote, (Quote.id == QuoteItem.quote_id) & (Quote.tenant_id == QuoteItem.tenant_id)).where(
            QuoteItem.tenant_id == tenant_id, QuoteItem.offer_id.is_not(None),
            Quote.status.in_(open_quotes))) or 0
        if count:
            found.append({"type": "catalog_items", "count": count,
                          "message": "Partidas del catálogo en cotizaciones abiertas."})
    return found


# ----------------------------------------------------------------------------
# Cambios de configuración
# ----------------------------------------------------------------------------

def _lock_tenant(tenant_id):
    tenant = db.session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if tenant is None:
        raise CapabilityError("tenant_not_found", 404)
    return tenant


def _upsert_module(tenant_id, code, state, source, actor_id):
    row = db.session.get(TenantModule, (tenant_id, code))
    if row is None:
        db.session.add(TenantModule(tenant_id=tenant_id, module_code=code, state=state, source=source,
                                    updated_by=actor_id, updated_at=now()))
        return None
    previous = row.state
    row.state, row.source, row.updated_by, row.updated_at = state, source, actor_id, now()
    return previous


def _materialize_legacy(tenant_id):
    """Convierte la configuración implícita de una organización anterior a v1.3.0 en filas."""
    if db.session.get(TenantOnboarding, tenant_id) is None and db.session.scalar(
            select(func.count()).select_from(TenantModule).where(TenantModule.tenant_id == tenant_id)) == 0:
        for code in OPTIONAL_MODULES:
            db.session.add(TenantModule(tenant_id=tenant_id, module_code=code,
                                        state="enabled" if code in LEGACY_MODULES else "disabled",
                                        source="legacy"))
        db.session.add(TenantOnboarding(tenant_id=tenant_id, status="legacy"))
        db.session.flush()


def set_tenant_modules(tenant_id, actor_id, changes, *, source="manual", commit=True):
    """Aplica {código: bool}. Valida códigos, plan, dependencias y operaciones activas.

    Habilitar agrega las dependencias necesarias. Deshabilitar nunca borra datos.
    """
    if not isinstance(changes, dict) or not changes:
        raise CapabilityError("invalid_modules", 422)
    _lock_tenant(tenant_id)
    ensure_module_rows()
    _materialize_legacy(tenant_id)
    invalidate(tenant_id)
    for code, value in changes.items():
        module = MODULES_BY_CODE.get(code)
        if module is None:
            raise CapabilityError("unknown_module", 422, module=code)
        if not isinstance(value, bool):
            raise CapabilityError("invalid_modules", 422, module=code)
        if module.essential:
            if value is False:
                raise CapabilityError("module_essential", 409, module=code)
            continue
        if module.status != AVAILABLE or code in _globally_inactive():
            if value:
                raise CapabilityError("module_unavailable", 409, module=code)
    snap = _snapshot(tenant_id)
    configured = dict(snap["configured"])
    to_enable = {c for c, v in changes.items() if v and c in OPTIONAL_MODULES}
    to_disable = {c for c, v in changes.items() if not v and c in OPTIONAL_MODULES}
    auto = resolve_module_dependencies(to_enable) - to_enable
    to_enable |= auto
    if to_enable & to_disable:
        conflict = sorted(to_enable & to_disable)
        raise CapabilityError("module_dependency_required", 409, modules=conflict,
                              reason="Un módulo habilitado depende de otro que intentas deshabilitar.")
    plan_allowed = snap["plan_allowed"]
    if plan_allowed is not None:
        locked = sorted(c for c in to_enable if c not in plan_allowed)
        if locked:
            raise CapabilityError("plan_upgrade_required", 403, modules=locked)
    final_enabled = ({c for c, s in configured.items() if s == "enabled"} | to_enable) - to_disable
    for code in sorted(to_disable):
        blocking = sorted(d for d in dependents_of(code) if d in final_enabled)
        if blocking:
            raise CapabilityError("module_dependency_required", 409, module=code, dependents=blocking,
                                  reason="Deshabilita primero los módulos que dependen de este.")
    rejected = {}
    for code in sorted(to_disable):
        if configured.get(code) == "enabled":
            ops = active_operations(tenant_id, code)
            if ops:
                rejected[code] = ops
    if rejected:
        db.session.rollback()
        for code, ops in rejected.items():
            _audit(actor_id, "module.disable_rejected", tenant_id, "module", code,
                   {"operations": [{"type": o["type"], "count": o["count"]} for o in ops]})
        db.session.commit()
        raise CapabilityError("module_has_active_operations", 409, modules=rejected)
    applied = {}
    for code in sorted(to_enable):
        previous = _upsert_module(tenant_id, code, "enabled", source, actor_id)
        if previous != "enabled":
            applied[code] = True
            _audit(actor_id, "module.enabled", tenant_id, "module", code,
                   {"previous": previous, "new": "enabled", "source": source,
                    "auto_dependency": code in auto})
    for code in sorted(to_disable):
        previous = _upsert_module(tenant_id, code, "disabled", source, actor_id)
        if previous == "enabled":
            applied[code] = False
            _audit(actor_id, "module.disabled", tenant_id, "module", code,
                   {"previous": previous, "new": "disabled", "source": source})
    if auto:
        _audit(actor_id, "module.dependency_resolved", tenant_id, "module", None,
               {"requested": sorted(to_enable - auto), "added": sorted(auto)})
    invalidate(tenant_id)
    if commit:
        db.session.commit()
    return {"applied": applied, "auto_enabled": sorted(auto)}


# ----------------------------------------------------------------------------
# Giros comerciales de la organización
# ----------------------------------------------------------------------------

def business_type_dict(bt, modules=None):
    return {
        "id": bt.id, "code": bt.code, "name": bt.name, "description": bt.description, "icon": bt.icon,
        "sort_order": bt.sort_order, "is_active": bt.is_active, "is_internal": bt.is_internal,
        "allows_custom_description": bt.allows_custom_description, "template_version": bt.template_version,
        "recommended_modules": sorted(modules) if modules is not None else None,
    }


def list_business_types(include_inactive=False, include_internal=False):
    query = select(BusinessType).order_by(BusinessType.sort_order, BusinessType.name)
    if not include_inactive:
        query = query.where(BusinessType.is_active.is_(True))
    if not include_internal:
        query = query.where(BusinessType.is_internal.is_(False))
    types = db.session.scalars(query).all()
    templates = {}
    for bt_id, code in db.session.execute(select(BusinessTypeModule.business_type_id,
                                                 BusinessTypeModule.module_code)).all():
        templates.setdefault(bt_id, set()).add(code)
    return [business_type_dict(bt, templates.get(bt.id, set())) for bt in types]


def tenant_business_types(tenant_id):
    rows = db.session.execute(select(TenantBusinessType, BusinessType).join(
        BusinessType, BusinessType.id == TenantBusinessType.business_type_id).where(
        TenantBusinessType.tenant_id == tenant_id).order_by(TenantBusinessType.is_primary.desc(),
                                                             BusinessType.sort_order)).all()
    return [{"code": bt.code, "name": bt.name, "icon": bt.icon, "is_primary": tbt.is_primary,
             "is_internal": bt.is_internal, "custom_description": tbt.custom_description} for tbt, bt in rows]


def _clean_business_types(items):
    if not isinstance(items, list) or not items or len(items) > 20:
        raise CapabilityError("invalid_business_types", 422)
    cleaned, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or set(item) - {"code", "is_primary", "custom_description"}:
            raise CapabilityError("invalid_business_types", 422)
        code = item.get("code")
        if not isinstance(code, str) or code in seen:
            raise CapabilityError("invalid_business_types", 422)
        seen.add(code)
        primary = item.get("is_primary", False)
        if not isinstance(primary, bool):
            raise CapabilityError("invalid_business_types", 422)
        custom = item.get("custom_description")
        if custom is not None and (not isinstance(custom, str) or len(custom.strip()) > 255):
            raise CapabilityError("invalid_custom_description", 422)
        cleaned.append({"code": code, "is_primary": primary,
                        "custom_description": custom.strip() if custom and custom.strip() else None})
    if sum(1 for i in cleaned if i["is_primary"]) != 1:
        raise CapabilityError("primary_business_type_required", 422)
    types = {bt.code: bt for bt in db.session.scalars(select(BusinessType).where(
        BusinessType.code.in_([i["code"] for i in cleaned]))).all()}
    for item in cleaned:
        bt = types.get(item["code"])
        if bt is None or not bt.is_active or bt.is_internal:
            raise CapabilityError("business_type_not_available", 422, business_type=item["code"])
        if item["custom_description"] and not bt.allows_custom_description:
            item["custom_description"] = None
        if bt.allows_custom_description and not item["custom_description"]:
            raise CapabilityError("custom_description_required", 422, business_type=item["code"])
        item["business_type"] = bt
    return cleaned


def set_business_types(tenant_id, actor_id, items, *, apply_recommendations=False, commit=True,
                       action="business_profile.updated"):
    """Reemplaza los giros de la organización. Nunca borra datos ni cambia módulos,
    salvo que se pida aplicar recomendaciones (solo habilita, nunca deshabilita)."""
    cleaned = _clean_business_types(items)
    _lock_tenant(tenant_id)
    previous = [t["code"] for t in tenant_business_types(tenant_id) if not t["is_internal"]]
    db.session.execute(TenantBusinessType.__table__.delete().where(
        TenantBusinessType.tenant_id == tenant_id,
        TenantBusinessType.business_type_id.in_(select(BusinessType.id).where(BusinessType.is_internal.is_(False)))))
    db.session.flush()
    for item in cleaned:
        db.session.add(TenantBusinessType(
            tenant_id=tenant_id, business_type_id=item["business_type"].id, is_primary=item["is_primary"],
            primary_flag=1 if item["is_primary"] else None, custom_description=item["custom_description"],
            created_by=actor_id, created_at=now()))
    db.session.flush()
    codes = [i["code"] for i in cleaned]
    _audit(actor_id, action, tenant_id, "tenant", tenant_id,
           {"previous": previous, "new": codes,
            "primary": next(i["code"] for i in cleaned if i["is_primary"])})
    result = {"business_types": codes, "enabled_modules": []}
    if apply_recommendations:
        recommended = get_recommended_modules(codes)
        plan_allowed = _snapshot(tenant_id)["plan_allowed"]
        if plan_allowed is not None:
            recommended = {c for c in recommended if c in plan_allowed}
        current = effective_modules(tenant_id) | {c for c, s in _snapshot(tenant_id)["configured"].items()
                                                  if s == "enabled"}
        missing = {c: True for c in recommended if c not in current}
        if missing:
            set_tenant_modules(tenant_id, actor_id, missing, source="manual", commit=False)
            result["enabled_modules"] = sorted(missing)
    invalidate(tenant_id)
    if commit:
        db.session.commit()
    return result


# ----------------------------------------------------------------------------
# Inicialización y onboarding
# ----------------------------------------------------------------------------

def ensure_module_rows():
    """Garantiza que el catálogo de módulos exista (la migración lo siembra; las bases
    creadas sin migraciones, como las pruebas en memoria, no)."""
    existing = set(db.session.scalars(select(Module.code)).all())
    missing = [m for m in MODULES if m.code not in existing]
    for m in missing:
        db.session.add(Module(code=m.code, name=m.name, description=m.description, icon=m.icon,
                              category=m.category, sort_order=m.sort_order, is_active=True))
    if missing:
        db.session.flush()


def initialize_tenant(tenant_id):
    """Organización nueva: módulos comunes activos y onboarding pendiente."""
    if db.session.get(TenantOnboarding, tenant_id) is not None:
        return
    ensure_module_rows()
    for code in OPTIONAL_MODULES:
        db.session.add(TenantModule(tenant_id=tenant_id, module_code=code,
                                    state="enabled" if code in DEFAULT_NEW_TENANT_MODULES else "disabled",
                                    source="default"))
    db.session.add(TenantOnboarding(tenant_id=tenant_id, status="pending", current_step=1))


def onboarding_status(tenant_id):
    row = db.session.get(TenantOnboarding, tenant_id)
    status = row.status if row else "legacy"
    return {
        "status": status, "required": status in ("pending", "in_progress"),
        "current_step": row.current_step if row else None, "draft": row.draft if row else None,
        "completed_at": row.completed_at.isoformat() if row and row.completed_at else None,
        "applied_templates": row.applied_templates if row else None,
        "business_types": tenant_business_types(tenant_id),
    }


def _clean_draft(draft):
    if not isinstance(draft, dict) or set(draft) - {"business_types", "modules", "step"}:
        raise CapabilityError("invalid_draft", 422)
    step = draft.get("step", 1)
    if isinstance(step, bool) or not isinstance(step, int) or not 1 <= step <= 6:
        raise CapabilityError("invalid_step", 422)
    modules = draft.get("modules", {})
    if not isinstance(modules, dict) or any(c not in MODULES_BY_CODE or not isinstance(v, bool)
                                            for c, v in modules.items()):
        raise CapabilityError("unknown_module", 422)
    types = draft.get("business_types", [])
    if not isinstance(types, list) or len(types) > 20:
        raise CapabilityError("invalid_business_types", 422)
    return {"business_types": types, "modules": modules, "step": step}


def save_onboarding_draft(tenant_id, actor_id, draft):
    clean = _clean_draft(draft)
    _lock_tenant(tenant_id)
    row = db.session.get(TenantOnboarding, tenant_id)
    if row is None:
        row = TenantOnboarding(tenant_id=tenant_id, status="legacy")
        db.session.add(row)
    if row.status == "completed":
        raise CapabilityError("onboarding_completed", 409)
    first = row.started_at is None
    if row.status in ("pending", "legacy"):
        row.status = "in_progress"
    row.started_at = row.started_at or now()
    row.current_step, row.draft = clean["step"], clean
    _audit(actor_id, "onboarding.started" if first else "onboarding.resumed", tenant_id, "tenant", tenant_id,
           {"step": clean["step"]})
    db.session.commit()
    return onboarding_status(tenant_id)


def preview(tenant_id, payload):
    """Vista previa sin guardar: módulos recomendados, resultado y restricciones del plan."""
    clean = _clean_draft(payload)
    codes = [i.get("code") for i in clean["business_types"] if isinstance(i, dict)]
    recommended = get_recommended_modules(codes)
    snap = _snapshot(tenant_id)
    if clean["modules"]:
        selected = {c for c, v in clean["modules"].items() if v and c in OPTIONAL_MODULES}
    else:
        selected = set(recommended)
    selected = resolve_module_dependencies(selected)
    plan_allowed = snap["plan_allowed"]
    modules = []
    for m in MODULES:
        if m.status == COMING_SOON:
            state = "coming_soon"
        elif m.essential:
            state = "essential"
        elif plan_allowed is not None and m.code not in plan_allowed:
            state = "requires_upgrade"
        elif m.code in selected:
            state = "selected"
        else:
            state = "available"
        modules.append({"code": m.code, "name": m.name, "description": m.description, "icon": m.icon,
                        "essential": m.essential, "recommended": m.code in recommended, "state": state,
                        "depends_on": list(m.depends_on), "routes": list(m.routes)})
    workspace = [{"code": m.code, "name": m.name, "routes": list(m.routes)}
                 for m in sorted(MODULES, key=lambda m: m.sort_order)
                 if m.status != COMING_SOON and (m.essential or (
                     m.code in selected and (plan_allowed is None or m.code in plan_allowed)))]
    return {"recommended": sorted(recommended), "modules": modules, "workspace": workspace}


def complete_onboarding(tenant_id, actor_id, payload):
    """Guarda giros y módulos en una sola transacción. Idempotente."""
    if not isinstance(payload, dict) or set(payload) - {"business_types", "modules"}:
        raise CapabilityError("invalid_payload", 422)
    _lock_tenant(tenant_id)
    row = db.session.get(TenantOnboarding, tenant_id)
    if row is not None and row.status == "completed":
        db.session.rollback()
        return {"already_completed": True, **onboarding_status(tenant_id)}
    if row is None:
        row = TenantOnboarding(tenant_id=tenant_id, status="legacy")
        db.session.add(row)
        db.session.flush()
    try:
        types_result = set_business_types(tenant_id, actor_id, payload.get("business_types"), commit=False,
                                          action="business_profile.selected")
        modules = payload.get("modules")
        if not isinstance(modules, dict):
            raise CapabilityError("invalid_modules", 422)
        changes = {c: v for c, v in modules.items() if MODULES_BY_CODE.get(c) is None or not
                   MODULES_BY_CODE[c].essential}
        if changes:
            set_tenant_modules(tenant_id, actor_id, changes, source="onboarding", commit=False)
        versions = dict(db.session.execute(select(BusinessType.code, BusinessType.template_version).where(
            BusinessType.code.in_(types_result["business_types"]))).all())
        row = db.session.get(TenantOnboarding, tenant_id)
        row.status, row.completed_at, row.completed_by = "completed", now(), actor_id
        row.applied_templates, row.draft = versions, None
        row.started_at = row.started_at or now()
        _audit(actor_id, "onboarding.completed", tenant_id, "tenant", tenant_id,
               {"business_types": types_result["business_types"], "templates": versions,
                "modules": sorted(c for c, v in changes.items() if v)})
        db.session.commit()
    except CapabilityError:
        db.session.rollback()
        raise
    invalidate(tenant_id)
    return {"already_completed": False, **onboarding_status(tenant_id)}


def capabilities_payload(tenant_id):
    snap = _snapshot(tenant_id)
    return {
        "modules": get_tenant_modules(tenant_id),
        "effective_modules": sorted(effective_modules(tenant_id)),
        "capabilities": get_effective_capabilities(tenant_id),
        "plan_restricted": snap["plan_allowed"] is not None,
        "enforcement": flag_enabled("modules.enforcement"),
        "onboarding": snap["onboarding"],
        "business_types": tenant_business_types(tenant_id),
    }
