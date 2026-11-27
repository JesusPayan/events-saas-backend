"""MOD-01: giros comerciales, módulos, configuración por organización y planes.

- ``business_types``: catálogo global de giros (administrable). Las plantillas de
  módulos recomendados se versionan con ``template_version``.
- ``modules``: copia administrable del registro en código (``app/modules_registry``):
  nombre, orden y estado global. Las dependencias y capacidades viven en código.
- ``tenant_business_types`` / ``tenant_modules`` / ``tenant_onboarding``: configuración
  de cada organización (siempre con ``tenant_id``).
- ``plan_modules``: módulos incluidos por plan. Un plan sin filas no restringe módulos
  (compatibilidad: no cambia las condiciones comerciales existentes).
- ``feature_flags``: activación progresiva controlada por la plataforma.
"""
from app.extensions import db
from app.models.identity import now

_PK = db.BigInteger().with_variant(db.Integer, "sqlite")

MODULE_STATES = ("enabled", "disabled")
ONBOARDING_STATES = ("pending", "in_progress", "completed", "legacy")


class BusinessType(db.Model):
    __tablename__ = "business_types"
    id = db.Column(_PK, primary_key=True, autoincrement=True)
    code = db.Column(db.String(40), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    icon = db.Column(db.String(40), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # Perfil interno (p. ej. LEGACY_COMPATIBILITY): nunca se ofrece a las organizaciones.
    is_internal = db.Column(db.Boolean, nullable=False, default=False)
    allows_custom_description = db.Column(db.Boolean, nullable=False, default=False)
    template_version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    updated_at = db.Column(db.DateTime, nullable=False, default=now, onupdate=now)
    created_by = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=True)
    updated_by = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=True)


class Module(db.Model):
    __tablename__ = "modules"
    code = db.Column(db.String(40), primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    icon = db.Column(db.String(40), nullable=True)
    category = db.Column(db.String(30), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    # Interruptor global de la plataforma (no borra nada; bloquea operaciones nuevas).
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=now, onupdate=now)
    updated_by = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=True)


class BusinessTypeModule(db.Model):
    __tablename__ = "business_type_modules"
    business_type_id = db.Column(db.BigInteger, db.ForeignKey("business_types.id", ondelete="CASCADE"),
                                 primary_key=True)
    module_code = db.Column(db.String(40), db.ForeignKey("modules.code"), primary_key=True)


class TenantBusinessType(db.Model):
    __tablename__ = "tenant_business_types"
    id = db.Column(_PK, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, db.ForeignKey("tenants.id"), nullable=False)
    business_type_id = db.Column(db.BigInteger, db.ForeignKey("business_types.id"), nullable=False)
    is_primary = db.Column(db.Boolean, nullable=False, default=False)
    # 1 solo para el giro principal; NULL en los demás (un principal por organización).
    primary_flag = db.Column(db.SmallInteger, nullable=True)
    custom_description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    created_by = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=True)
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "business_type_id", name="uq_tenant_business_type"),
        db.UniqueConstraint("tenant_id", "primary_flag", name="uq_tenant_primary_business_type"),
        db.Index("ix_tenant_business_types_type", "business_type_id"),
    )


class TenantModule(db.Model):
    __tablename__ = "tenant_modules"
    tenant_id = db.Column(db.BigInteger, db.ForeignKey("tenants.id"), primary_key=True)
    module_code = db.Column(db.String(40), db.ForeignKey("modules.code"), primary_key=True)
    state = db.Column(db.String(20), nullable=False, default="enabled")
    source = db.Column(db.String(20), nullable=False, default="manual")
    updated_at = db.Column(db.DateTime, nullable=False, default=now, onupdate=now)
    updated_by = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=True)
    __table_args__ = (
        db.CheckConstraint("state IN ('enabled','disabled')", name="ck_tenant_modules_state"),
        db.CheckConstraint("source IN ('legacy','default','onboarding','manual')", name="ck_tenant_modules_source"),
        db.Index("ix_tenant_modules_module_state", "module_code", "state"),
    )


class TenantOnboarding(db.Model):
    __tablename__ = "tenant_onboarding"
    tenant_id = db.Column(db.BigInteger, db.ForeignKey("tenants.id"), primary_key=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    current_step = db.Column(db.Integer, nullable=False, default=1)
    # Borrador del asistente (selección en curso). JSON justificado: estado transitorio
    # del formulario; al completar, la configuración se guarda normalizada.
    draft = db.Column(db.JSON, nullable=True)
    # Instantánea de las plantillas aplicadas: {código de giro: versión}.
    applied_templates = db.Column(db.JSON, nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    completed_by = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=now, onupdate=now)
    __table_args__ = (
        db.CheckConstraint("status IN ('pending','in_progress','completed','legacy')",
                           name="ck_tenant_onboarding_status"),
    )


class PlanModule(db.Model):
    __tablename__ = "plan_modules"
    plan_id = db.Column(db.BigInteger, db.ForeignKey("billing_plans.id", ondelete="CASCADE"), primary_key=True)
    module_code = db.Column(db.String(40), db.ForeignKey("modules.code"), primary_key=True)


class FeatureFlag(db.Model):
    __tablename__ = "feature_flags"
    code = db.Column(db.String(60), primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    description = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=now, onupdate=now)
    updated_by = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=True)
