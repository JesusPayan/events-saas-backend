"""MOD-01: API de giros comerciales, módulos, capacidades y onboarding.

Errores de negocio (minúsculas, como el resto de la API):
module_disabled, plan_upgrade_required, module_unavailable, module_dependency_required,
module_has_active_operations, module_essential, unknown_module, business_type_not_available,
primary_business_type_required, onboarding_completed.
"""
from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, select

from app.extensions import db
from app.models import Tenant
from app.models.billing import BillingPlan
from app.models.identity import now
from app.models.modules import (
    BusinessType, BusinessTypeModule, FeatureFlag, Module, PlanModule, TenantBusinessType, TenantModule,
    TenantOnboarding,
)
from app.modules_registry import MODULES, MODULES_BY_CODE, OPTIONAL_MODULES
from app.security import authenticate, platform_permission, tenant_permission
from app.services import capability_service as cap
from app.services.capability_service import CapabilityError
from app.services.platform_service import record_audit

bp = Blueprint("modules", __name__)


def _error(exc):
    return jsonify(error=exc.code, **exc.extra), exc.status


def _body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise CapabilityError("invalid_json", 400)
    return body


def _module_catalog():
    return [{"code": m.code, "name": m.name, "description": m.description, "icon": m.icon,
             "category": m.category, "sort_order": m.sort_order, "essential": m.essential,
             "configurable": m.configurable, "depends_on": list(m.depends_on),
             "capabilities": list(m.capabilities), "availability": m.status, "min_version": m.min_version,
             "routes": list(m.routes)} for m in MODULES]


# ----------------------------------------------------------------------------
# Catálogos públicos (con sesión)
# ----------------------------------------------------------------------------

@bp.get("/business-types")
@authenticate
def business_types():
    return jsonify(items=cap.list_business_types()), 200


@bp.get("/modules")
@authenticate
def modules():
    return jsonify(items=_module_catalog()), 200


# ----------------------------------------------------------------------------
# Organización actual
# ----------------------------------------------------------------------------

@bp.get("/tenants/current/business-types")
@tenant_permission("tenant.read")
def current_business_types():
    return jsonify(items=cap.tenant_business_types(g.tenant_id)), 200


@bp.patch("/tenants/current/business-types")
@tenant_permission("members.manage")
def update_business_types():
    try:
        body = _body()
        if set(body) - {"items", "apply_recommendations"}:
            raise CapabilityError("invalid_fields", 422)
        apply = body.get("apply_recommendations", False)
        if not isinstance(apply, bool):
            raise CapabilityError("invalid_apply_recommendations", 422)
        result = cap.set_business_types(g.tenant_id, g.user.id, body.get("items"), apply_recommendations=apply)
    except CapabilityError as exc:
        db.session.rollback()
        return _error(exc)
    return jsonify(result=result, items=cap.tenant_business_types(g.tenant_id),
                   recommended=sorted(cap.get_recommended_modules(result["business_types"]))), 200


@bp.get("/tenants/current/modules")
@tenant_permission("tenant.read")
def current_modules():
    return jsonify(items=cap.get_tenant_modules(g.tenant_id)), 200


@bp.patch("/tenants/current/modules")
@tenant_permission("members.manage")
def update_modules():
    try:
        body = _body()
        if set(body) != {"modules"}:
            raise CapabilityError("invalid_fields", 422)
        result = cap.set_tenant_modules(g.tenant_id, g.user.id, body["modules"])
    except CapabilityError as exc:
        db.session.rollback()
        return _error(exc)
    return jsonify(result=result, items=cap.get_tenant_modules(g.tenant_id)), 200


@bp.get("/tenants/current/modules/<code>/impact")
@tenant_permission("tenant.read")
def module_impact(code):
    """Qué impide deshabilitar un módulo (operaciones activas y módulos dependientes)."""
    if code not in MODULES_BY_CODE:
        return jsonify(error="unknown_module"), 404
    from app.modules_registry import dependents_of
    enabled = cap.effective_modules(g.tenant_id)
    return jsonify(module=code, operations=cap.active_operations(g.tenant_id, code),
                   dependents=sorted(d for d in dependents_of(code) if d in enabled)), 200


@bp.get("/tenants/current/capabilities")
@tenant_permission("tenant.read")
def current_capabilities():
    return jsonify(cap.capabilities_payload(g.tenant_id)), 200


# ----------------------------------------------------------------------------
# Onboarding (independiente por organización)
# ----------------------------------------------------------------------------

@bp.get("/onboarding/status")
@tenant_permission("tenant.read")
def onboarding_status():
    status = cap.onboarding_status(g.tenant_id)
    status["can_manage"] = _can_manage()
    return jsonify(status), 200


def _can_manage():
    from app.security import _role_allows
    membership = getattr(g, "membership", None)
    return bool(membership and _role_allows(membership.role_id, "members.manage"))


@bp.put("/onboarding/draft")
@tenant_permission("members.manage")
def onboarding_draft():
    try:
        return jsonify(cap.save_onboarding_draft(g.tenant_id, g.user.id, _body())), 200
    except CapabilityError as exc:
        db.session.rollback()
        return _error(exc)


@bp.post("/onboarding/preview")
@tenant_permission("tenant.read")
def onboarding_preview():
    try:
        return jsonify(cap.preview(g.tenant_id, _body())), 200
    except CapabilityError as exc:
        return _error(exc)


@bp.post("/onboarding/complete")
@tenant_permission("members.manage")
def onboarding_complete():
    try:
        result = cap.complete_onboarding(g.tenant_id, g.user.id, _body())
    except CapabilityError as exc:
        db.session.rollback()
        return _error(exc)
    return jsonify(result), 200


# ----------------------------------------------------------------------------
# Plataforma: giros, plantillas, módulos, planes, flags y adopción
# ----------------------------------------------------------------------------

_BT_FIELDS = {"code", "name", "description", "icon", "sort_order", "is_active", "allows_custom_description"}


def _clean_bt(body, *, creating):
    if set(body) - _BT_FIELDS or (not creating and "code" in body):
        raise CapabilityError("invalid_fields", 422)
    data = {}
    if creating:
        code = body.get("code")
        if not isinstance(code, str) or not code.replace("_", "").isalnum() or not code.isupper() \
                or not 3 <= len(code) <= 40:
            raise CapabilityError("invalid_code", 422)
        data["code"] = code
    for field, limit in (("name", 120), ("description", 500), ("icon", 40)):
        if field in body or (creating and field == "name"):
            value = body.get(field)
            if value is None and field != "name":
                data[field] = None
                continue
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
                raise CapabilityError(f"invalid_{field}", 422)
            data[field] = value.strip()
    if "sort_order" in body:
        if isinstance(body["sort_order"], bool) or not isinstance(body["sort_order"], int):
            raise CapabilityError("invalid_sort_order", 422)
        data["sort_order"] = body["sort_order"]
    for flag in ("is_active", "allows_custom_description"):
        if flag in body:
            if not isinstance(body[flag], bool):
                raise CapabilityError(f"invalid_{flag}", 422)
            data[flag] = body[flag]
    return data


@bp.get("/platform/business-types")
@platform_permission("platform.catalog.manage")
def platform_business_types():
    counts = dict(db.session.execute(select(TenantBusinessType.business_type_id, func.count())
                                     .group_by(TenantBusinessType.business_type_id)).all())
    items = cap.list_business_types(include_inactive=True, include_internal=True)
    for item in items:
        item["organizations"] = counts.get(item["id"], 0)
    return jsonify(items=items), 200


@bp.post("/platform/business-types")
@platform_permission("platform.catalog.manage")
def platform_create_business_type():
    try:
        data = _clean_bt(_body(), creating=True)
        if db.session.scalar(select(BusinessType.id).where(BusinessType.code == data["code"])):
            raise CapabilityError("code_taken", 409)
        bt = BusinessType(**data, created_by=g.user.id, updated_by=g.user.id, template_version=1)
        db.session.add(bt)
        db.session.flush()
        record_audit(g.user.id, "business_type.create", target_type="business_type", target_id=bt.id,
                     details={"code": bt.code})
        db.session.commit()
    except CapabilityError as exc:
        db.session.rollback()
        return _error(exc)
    return jsonify(item=cap.business_type_dict(bt, set())), 201


@bp.patch("/platform/business-types/<int:type_id>")
@platform_permission("platform.catalog.manage")
def platform_update_business_type(type_id):
    try:
        bt = db.session.get(BusinessType, type_id)
        if bt is None or bt.is_internal:
            raise CapabilityError("business_type_not_found", 404)
        data = _clean_bt(_body(), creating=False)
        before = {k: getattr(bt, k) for k in data}
        for key, value in data.items():
            setattr(bt, key, value)
        bt.updated_by = g.user.id
        record_audit(g.user.id, "business_type.update", target_type="business_type", target_id=bt.id,
                     details={"before": before, "after": data})
        db.session.commit()
    except CapabilityError as exc:
        db.session.rollback()
        return _error(exc)
    return jsonify(item=cap.business_type_dict(bt)), 200


@bp.get("/platform/business-types/<int:type_id>/modules")
@platform_permission("platform.catalog.manage")
def platform_business_type_modules(type_id):
    bt = db.session.get(BusinessType, type_id)
    if bt is None:
        return jsonify(error="business_type_not_found"), 404
    codes = db.session.scalars(select(BusinessTypeModule.module_code).where(
        BusinessTypeModule.business_type_id == type_id)).all()
    return jsonify(modules=sorted(codes), template_version=bt.template_version), 200


@bp.put("/platform/business-types/<int:type_id>/modules")
@platform_permission("platform.catalog.manage")
def platform_set_business_type_modules(type_id):
    """Nueva versión de la plantilla. No cambia la configuración de organizaciones existentes."""
    try:
        bt = db.session.scalar(select(BusinessType).where(BusinessType.id == type_id).with_for_update())
        if bt is None or bt.is_internal:
            raise CapabilityError("business_type_not_found", 404)
        body = _body()
        modules = body.get("modules")
        if set(body) != {"modules"} or not isinstance(modules, list) or len(set(modules)) != len(modules):
            raise CapabilityError("invalid_modules", 422)
        unknown = [c for c in modules if c not in OPTIONAL_MODULES]
        if unknown:
            raise CapabilityError("unknown_module", 422, modules=unknown)
        resolved = cap.resolve_module_dependencies(set(modules))
        before = sorted(db.session.scalars(select(BusinessTypeModule.module_code).where(
            BusinessTypeModule.business_type_id == type_id)).all())
        db.session.execute(BusinessTypeModule.__table__.delete().where(
            BusinessTypeModule.business_type_id == type_id))
        for code in sorted(resolved):
            db.session.add(BusinessTypeModule(business_type_id=type_id, module_code=code))
        bt.template_version += 1
        bt.updated_by = g.user.id
        record_audit(g.user.id, "module_template.updated", target_type="business_type", target_id=bt.id,
                     details={"code": bt.code, "before": before, "after": sorted(resolved),
                              "version": bt.template_version})
        db.session.commit()
    except CapabilityError as exc:
        db.session.rollback()
        return _error(exc)
    return jsonify(modules=sorted(resolved), template_version=bt.template_version), 200


@bp.get("/platform/modules")
@platform_permission("platform.catalog.manage")
def platform_modules():
    rows = {m.code: m for m in db.session.scalars(select(Module)).all()}
    usage = dict(db.session.execute(select(TenantModule.module_code, func.count()).where(
        TenantModule.state == "enabled").group_by(TenantModule.module_code)).all())
    plans = {}
    for plan_code, module_code in db.session.execute(select(BillingPlan.code, PlanModule.module_code).join(
            BillingPlan, BillingPlan.id == PlanModule.plan_id)).all():
        plans.setdefault(module_code, []).append(plan_code)
    total_tenants = db.session.scalar(select(func.count()).select_from(Tenant)) or 0
    items = []
    for item in _module_catalog():
        row = rows.get(item["code"])
        item["is_active"] = row.is_active if row else True
        # Los esenciales no tienen fila por empresa: siempre están activos en todas.
        item["organizations"] = total_tenants if item.get("essential") else usage.get(item["code"], 0)
        item["plans"] = sorted(plans.get(item["code"], []))
        items.append(item)
    flags = [{"code": f.code, "enabled": f.enabled, "description": f.description}
             for f in db.session.scalars(select(FeatureFlag).order_by(FeatureFlag.code)).all()]
    return jsonify(items=items, feature_flags=flags), 200


@bp.patch("/platform/modules/<code>")
@platform_permission("platform.catalog.manage")
def platform_update_module(code):
    """Interruptor global. No borra datos; bloquea operaciones nuevas del módulo."""
    try:
        module = MODULES_BY_CODE.get(code)
        row = db.session.get(Module, code)
        if module is None or row is None:
            raise CapabilityError("unknown_module", 404)
        body = _body()
        if set(body) != {"is_active"} or not isinstance(body["is_active"], bool):
            raise CapabilityError("invalid_fields", 422)
        if module.essential and not body["is_active"]:
            raise CapabilityError("module_essential", 409)
        previous, row.is_active, row.updated_by = row.is_active, body["is_active"], g.user.id
        record_audit(g.user.id, "module.global_state", target_type="module", target_id=code,
                     details={"previous": previous, "new": body["is_active"]})
        db.session.commit()
    except CapabilityError as exc:
        db.session.rollback()
        return _error(exc)
    return jsonify(code=code, is_active=row.is_active), 200


@bp.get("/platform/plans/<int:plan_id>/modules")
@platform_permission("platform.plans.manage")
def platform_plan_modules(plan_id):
    plan = db.session.get(BillingPlan, plan_id)
    if plan is None:
        return jsonify(error="plan_not_found"), 404
    codes = db.session.scalars(select(PlanModule.module_code).where(PlanModule.plan_id == plan_id)).all()
    return jsonify(plan={"id": plan.id, "code": plan.code, "name": plan.name}, modules=sorted(codes),
                   restricted=bool(codes)), 200


@bp.get("/platform/plans")
@platform_permission("platform.plans.manage")
def platform_plans():
    plans = db.session.scalars(select(BillingPlan).order_by(BillingPlan.id)).all()
    restricted = dict(db.session.execute(select(PlanModule.plan_id, func.count()).group_by(PlanModule.plan_id)).all())
    return jsonify(items=[{"id": p.id, "code": p.code, "name": p.name, "active": p.active,
                           "restricted_modules": restricted.get(p.id, 0)} for p in plans]), 200


@bp.put("/platform/plans/<int:plan_id>/modules")
@platform_permission("platform.plans.manage")
def platform_set_plan_modules(plan_id):
    """Módulos incluidos por plan (solo dueño). Lista vacía = el plan no restringe módulos.
    No cambia precios ni condiciones de cobro; no borra datos de nadie."""
    try:
        plan = db.session.scalar(select(BillingPlan).where(BillingPlan.id == plan_id).with_for_update())
        if plan is None:
            raise CapabilityError("plan_not_found", 404)
        body = _body()
        modules = body.get("modules")
        if set(body) != {"modules"} or not isinstance(modules, list) or len(set(modules)) != len(modules):
            raise CapabilityError("invalid_modules", 422)
        unknown = [c for c in modules if c not in OPTIONAL_MODULES]
        if unknown:
            raise CapabilityError("unknown_module", 422, modules=unknown)
        resolved = cap.resolve_module_dependencies(set(modules)) if modules else set()
        before = sorted(db.session.scalars(select(PlanModule.module_code).where(PlanModule.plan_id == plan_id)).all())
        db.session.execute(PlanModule.__table__.delete().where(PlanModule.plan_id == plan_id))
        for code in sorted(resolved):
            db.session.add(PlanModule(plan_id=plan_id, module_code=code))
        record_audit(g.user.id, "plan.entitlements_updated", target_type="billing_plan", target_id=plan_id,
                     details={"plan": plan.code, "before": before, "after": sorted(resolved)})
        db.session.commit()
    except CapabilityError as exc:
        db.session.rollback()
        return _error(exc)
    return jsonify(modules=sorted(resolved), restricted=bool(resolved)), 200


@bp.patch("/platform/feature-flags/<code>")
@platform_permission("platform.flags.manage")
def platform_update_flag(code):
    flag = db.session.get(FeatureFlag, code)
    if flag is None:
        return jsonify(error="unknown_feature_flag"), 404
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {"enabled"} or not isinstance(body["enabled"], bool):
        return jsonify(error="invalid_fields"), 422
    previous, flag.enabled, flag.updated_by, flag.updated_at = flag.enabled, body["enabled"], g.user.id, now()
    record_audit(g.user.id, "feature_flag.updated", target_type="feature_flag", target_id=code,
                 details={"previous": previous, "new": body["enabled"]})
    db.session.commit()
    return jsonify(code=code, enabled=flag.enabled), 200


@bp.get("/platform/modules/adoption")
@platform_permission("platform.catalog.manage", "platform.orgs.manage")
def platform_adoption():
    """Estadísticas agregadas (sin datos de organizaciones individuales)."""
    by_type = [{"code": code, "name": name, "organizations": count} for code, name, count in db.session.execute(
        select(BusinessType.code, BusinessType.name, func.count(TenantBusinessType.id))
        .join(TenantBusinessType, TenantBusinessType.business_type_id == BusinessType.id)
        .where(BusinessType.is_internal.is_(False))
        .group_by(BusinessType.code, BusinessType.name).order_by(func.count(TenantBusinessType.id).desc())).all()]
    primary = [{"code": code, "organizations": count} for code, count in db.session.execute(
        select(BusinessType.code, func.count(TenantBusinessType.id))
        .join(TenantBusinessType, TenantBusinessType.business_type_id == BusinessType.id)
        .where(TenantBusinessType.is_primary.is_(True))
        .group_by(BusinessType.code).order_by(func.count(TenantBusinessType.id).desc())).all()]
    modules_enabled = [{"code": code, "organizations": count} for code, count in db.session.execute(
        select(TenantModule.module_code, func.count()).where(TenantModule.state == "enabled")
        .group_by(TenantModule.module_code).order_by(func.count().desc())).all()]
    onboarding = dict(db.session.execute(select(TenantOnboarding.status, func.count())
                                         .group_by(TenantOnboarding.status)).all())
    total = db.session.scalar(select(func.count(Tenant.id))) or 0
    # Abandono: organizaciones que empezaron y no terminan tras 7 días.
    from datetime import timedelta
    stale = db.session.scalar(select(func.count()).select_from(TenantOnboarding).where(
        TenantOnboarding.status == "in_progress", TenantOnboarding.started_at < now() - timedelta(days=7))) or 0
    # Distribución de planes por giro principal (planes vigentes).
    from app.models.billing import BillingPlanPrice, TenantSubscription
    plans_by_type = [{"business_type": code, "plan": plan, "organizations": count}
                     for code, plan, count in db.session.execute(
        select(BusinessType.code, BillingPlan.code, func.count(func.distinct(TenantSubscription.tenant_id)))
        .join(TenantBusinessType, TenantBusinessType.business_type_id == BusinessType.id)
        .join(TenantSubscription, TenantSubscription.tenant_id == TenantBusinessType.tenant_id)
        .join(BillingPlanPrice, BillingPlanPrice.id == TenantSubscription.plan_price_id)
        .join(BillingPlan, BillingPlan.id == BillingPlanPrice.plan_id)
        .where(TenantBusinessType.is_primary.is_(True), TenantSubscription.status.in_(("active", "trialing")))
        .group_by(BusinessType.code, BillingPlan.code)).all()]
    return jsonify(organizations=total, by_business_type=by_type, primary_business_type=primary,
                   modules_enabled=modules_enabled, onboarding=onboarding, onboarding_stale=stale,
                   plans_by_business_type=plans_by_type), 200
