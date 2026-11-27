"""MOD-01: giros comerciales, módulos, configuración por organización, planes y flags.

Aditiva y no destructiva:
- Crea las tablas del catálogo global y de la configuración por organización.
- Siembra módulos (desde el registro en código), 18 giros con sus plantillas v1, el
  perfil interno LEGACY_COMPATIBILITY y el flag ``modules.enforcement``.
- Organizaciones existentes: perfil de compatibilidad, onboarding ``legacy`` y los
  mismos módulos que ya podían usar (todos los disponibles hasta v1.2.0). No se
  habilita ninguna funcionalidad de pago ni se cambian planes.
- ``plan_modules`` queda vacía: los planes no restringen módulos hasta que el dueño
  de plataforma lo configure.

Revision ID: c08000000001
Revises: c07000000001
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = 'c08000000001'
down_revision = 'c07000000001'
branch_labels = None
depends_on = None

PK = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def upgrade():
    op.create_table(
        'business_types',
        sa.Column('id', PK, primary_key=True, autoincrement=True),
        sa.Column('code', sa.String(40), nullable=False, unique=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('icon', sa.String(40), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('is_internal', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('allows_custom_description', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('template_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
    )
    op.create_table(
        'modules',
        sa.Column('code', sa.String(40), primary_key=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('icon', sa.String(40), nullable=True),
        sa.Column('category', sa.String(30), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
    )
    op.create_table(
        'business_type_modules',
        sa.Column('business_type_id', sa.BigInteger(), sa.ForeignKey('business_types.id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('module_code', sa.String(40), sa.ForeignKey('modules.code'), primary_key=True),
    )
    op.create_table(
        'tenant_business_types',
        sa.Column('id', PK, primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.BigInteger(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('business_type_id', sa.BigInteger(), sa.ForeignKey('business_types.id'), nullable=False),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('primary_flag', sa.SmallInteger(), nullable=True),
        sa.Column('custom_description', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.UniqueConstraint('tenant_id', 'business_type_id', name='uq_tenant_business_type'),
        sa.UniqueConstraint('tenant_id', 'primary_flag', name='uq_tenant_primary_business_type'),
    )
    op.create_index('ix_tenant_business_types_type', 'tenant_business_types', ['business_type_id'])
    op.create_table(
        'tenant_modules',
        sa.Column('tenant_id', sa.BigInteger(), sa.ForeignKey('tenants.id'), primary_key=True),
        sa.Column('module_code', sa.String(40), sa.ForeignKey('modules.code'), primary_key=True),
        sa.Column('state', sa.String(20), nullable=False, server_default='enabled'),
        sa.Column('source', sa.String(20), nullable=False, server_default='manual'),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.CheckConstraint("state IN ('enabled','disabled')", name='ck_tenant_modules_state'),
        sa.CheckConstraint("source IN ('legacy','default','onboarding','manual')", name='ck_tenant_modules_source'),
    )
    op.create_index('ix_tenant_modules_module_state', 'tenant_modules', ['module_code', 'state'])
    op.create_table(
        'tenant_onboarding',
        sa.Column('tenant_id', sa.BigInteger(), sa.ForeignKey('tenants.id'), primary_key=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('current_step', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('draft', sa.JSON(), nullable=True),
        sa.Column('applied_templates', sa.JSON(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('completed_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('pending','in_progress','completed','legacy')",
                           name='ck_tenant_onboarding_status'),
    )
    op.create_table(
        'plan_modules',
        sa.Column('plan_id', sa.BigInteger(), sa.ForeignKey('billing_plans.id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('module_code', sa.String(40), sa.ForeignKey('modules.code'), primary_key=True),
    )
    op.create_table(
        'feature_flags',
        sa.Column('code', sa.String(60), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('description', sa.String(255), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
    )

    # ------------------------------------------------------------------ datos
    from app.business_profiles_data import BUSINESS_TYPES, FEATURE_FLAGS, LEGACY_CODE, LEGACY_MODULES
    from app.modules_registry import MODULES, OPTIONAL_MODULES

    conn = op.get_bind()
    now = _now()
    for m in MODULES:
        conn.execute(sa.text(
            "INSERT INTO modules (code, name, description, icon, category, sort_order, is_active, updated_at) "
            "VALUES (:code, :name, :description, :icon, :category, :sort_order, :active, :now)"),
            {"code": m.code, "name": m.name, "description": m.description, "icon": m.icon,
             "category": m.category, "sort_order": m.sort_order, "active": True, "now": now})

    def insert_type(code, name, description, icon, order, modules, custom, internal):
        conn.execute(sa.text(
            "INSERT INTO business_types (code, name, description, icon, sort_order, is_active, is_internal, "
            "allows_custom_description, template_version, created_at, updated_at) "
            "VALUES (:code, :name, :description, :icon, :order, :active, :internal, :custom, 1, :now, :now)"),
            {"code": code, "name": name, "description": description, "icon": icon, "order": order,
             "active": True, "internal": internal, "custom": custom, "now": now})
        type_id = conn.execute(sa.text("SELECT id FROM business_types WHERE code = :code"), {"code": code}).scalar()
        for module_code in modules:
            conn.execute(sa.text("INSERT INTO business_type_modules (business_type_id, module_code) "
                                 "VALUES (:id, :code)"), {"id": type_id, "code": module_code})
        return type_id

    for code, name, description, icon, order, modules, custom in BUSINESS_TYPES:
        insert_type(code, name, description, icon, order, modules, custom, False)
    legacy_id = insert_type(LEGACY_CODE, "Compatibilidad (organizaciones anteriores a v1.3.0)",
                            "Perfil interno: conserva los módulos previos.", "shield", 9999, LEGACY_MODULES,
                            False, True)
    for code, enabled, description in FEATURE_FLAGS:
        conn.execute(sa.text("INSERT INTO feature_flags (code, enabled, description, updated_at) "
                             "VALUES (:code, :enabled, :description, :now)"),
                     {"code": code, "enabled": enabled, "description": description, "now": now})

    # Organizaciones existentes: mismos módulos que tenían, sin onboarding obligatorio.
    tenant_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM tenants")).fetchall()]
    for tenant_id in tenant_ids:
        conn.execute(sa.text("INSERT INTO tenant_onboarding (tenant_id, status, current_step, updated_at) "
                             "VALUES (:tenant, 'legacy', 1, :now)"), {"tenant": tenant_id, "now": now})
        conn.execute(sa.text("INSERT INTO tenant_business_types (tenant_id, business_type_id, is_primary, "
                             "primary_flag, created_at) VALUES (:tenant, :type, :primary, NULL, :now)"),
                     {"tenant": tenant_id, "type": legacy_id, "primary": False, "now": now})
        for module_code in sorted(OPTIONAL_MODULES):
            conn.execute(sa.text(
                "INSERT INTO tenant_modules (tenant_id, module_code, state, source, updated_at) "
                "VALUES (:tenant, :code, :state, 'legacy', :now)"),
                {"tenant": tenant_id, "code": module_code,
                 "state": "enabled" if module_code in LEGACY_MODULES else "disabled", "now": now})


def downgrade():
    # No toca datos operativos (clientes, eventos, cotizaciones, inventario...).
    for table in ('feature_flags', 'plan_modules', 'tenant_onboarding', 'tenant_modules',
                  'tenant_business_types', 'business_type_modules', 'modules', 'business_types'):
        op.drop_table(table)
