"""ROLES-01 + CAT-01: roles administrativos con alcance, auditoría, accesos
delegados, promotores, catálogo de servicios y partidas mixtas.

Aditiva: crea tablas nuevas y agrega columnas con valores por defecto. No
modifica identificadores, relaciones ni importes existentes:
- Las partidas actuales quedan con ``price_status='confirmed'`` y sin
  confirmación pendiente, por lo que sus totales no cambian.
- Los roles existentes reciben ``catalog.read``/``catalog.manage`` según su nivel.
- Siembra las categorías iniciales del catálogo.

Revision ID: c06000000001
Revises: b05000000001
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = 'c06000000001'
down_revision = 'b05000000001'
branch_labels = None
depends_on = None

PK = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')

CATEGORIES = (
    ("renta-de-mobiliario", "Renta de mobiliario", True, False),
    ("cocteleria-y-barras-de-bebidas", "Coctelería y barras de bebidas", False, False),
    ("barras-de-postres", "Barras de postres", False, False),
    ("snacks-y-mesas-de-botanas", "Snacks y mesas de botanas", False, False),
    ("tablas-y-barras-de-quesos", "Tablas y barras de quesos", False, False),
    ("banquetes-y-catering", "Banquetes y catering", False, False),
    ("fotografia", "Fotografía", False, False),
    ("video", "Video", False, False),
    ("musica-en-vivo", "Música en vivo", False, False),
    ("dj-y-musica-grabada", "DJ y música grabada", False, False),
    ("pirotecnia-y-efectos-especiales", "Pirotecnia y espectáculos de efectos especiales", False, True),
    ("otros-servicios", "Otros servicios", False, False),
)
# Mapeo conservador: quien ya administraba inventario administra el catálogo.
NEW_PERMISSIONS = {
    "catalog.read": ("owner", "admin", "staff", "viewer"),
    "catalog.manage": ("owner", "admin", "staff"),
}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def upgrade():
    op.create_table(
        'platform_role_assignments',
        sa.Column('id', PK, primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('role_key', sa.String(30), nullable=False),
        sa.Column('scope_type', sa.String(20), nullable=False, server_default='platform'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('active_flag', sa.SmallInteger(), nullable=True),
        sa.Column('granted_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('granted_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "role_key IN ('platform_owner','platform_admin','promoter','support','finance','auditor')",
            name='ck_platform_role_key'),
        sa.CheckConstraint("status IN ('active','revoked')", name='ck_platform_role_status'),
        sa.CheckConstraint("scope_type IN ('platform')", name='ck_platform_role_scope'),
        sa.UniqueConstraint('user_id', 'role_key', 'active_flag', name='uq_platform_role_active'),
    )
    op.create_index('ix_platform_roles_role_status', 'platform_role_assignments', ['role_key', 'status'])

    op.create_table(
        'platform_invitations',
        sa.Column('id', PK, primary_key=True, autoincrement=True),
        sa.Column('email', sa.String(254), nullable=False),
        sa.Column('role_key', sa.String(30), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('invited_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('accepted_user_id', sa.BigInteger(), sa.ForeignKey('users.id')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('accepted_at', sa.DateTime()),
        sa.CheckConstraint("status IN ('pending','accepted','revoked')", name='ck_platform_invitation_status'),
    )
    op.create_index('ix_platform_invitations_email', 'platform_invitations', ['email'])

    op.create_table(
        'audit_events',
        sa.Column('id', PK, primary_key=True, autoincrement=True),
        sa.Column('actor_user_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('action', sa.String(60), nullable=False),
        sa.Column('scope_type', sa.String(20), nullable=False),
        sa.Column('tenant_id', sa.BigInteger(), sa.ForeignKey('tenants.id'), nullable=True),
        sa.Column('target_type', sa.String(40), nullable=True),
        sa.Column('target_id', sa.String(64), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("scope_type IN ('platform','tenant')", name='ck_audit_scope'),
    )
    op.create_index('ix_audit_events_tenant_created', 'audit_events', ['tenant_id', 'created_at'])
    op.create_index('ix_audit_events_action_created', 'audit_events', ['action', 'created_at'])
    op.create_index('ix_audit_events_actor', 'audit_events', ['actor_user_id'])

    op.create_table(
        'tenant_access_grants',
        sa.Column('id', PK, primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.BigInteger(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('grantee_user_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('purpose', sa.String(20), nullable=False),
        sa.Column('access_level', sa.String(20), nullable=False, server_default='read_only'),
        sa.Column('reason', sa.String(500), nullable=True),
        sa.Column('granted_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('granted_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("purpose IN ('support','training')", name='ck_access_grant_purpose'),
        sa.CheckConstraint("access_level IN ('read_only')", name='ck_access_grant_level'),
    )
    op.create_index('ix_access_grants_tenant_user', 'tenant_access_grants', ['tenant_id', 'grantee_user_id'])

    op.create_table(
        'promoter_referral_codes',
        sa.Column('id', PK, primary_key=True, autoincrement=True),
        sa.Column('promoter_user_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False, unique=True),
        sa.Column('code', sa.String(16), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_table(
        'promoter_prospects',
        sa.Column('id', PK, primary_key=True, autoincrement=True),
        sa.Column('promoter_user_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('company_name', sa.String(180), nullable=False),
        sa.Column('contact_name', sa.String(180), nullable=True),
        sa.Column('contact_email', sa.String(254), nullable=True),
        sa.Column('phone', sa.String(40), nullable=True),
        sa.Column('notes', sa.String(1000), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('tenant_id', sa.BigInteger(), sa.ForeignKey('tenants.id'), nullable=True),
        sa.Column('invited_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('prospect','invited','registered','discarded')",
                           name='ck_promoter_prospect_status'),
    )
    op.create_index('ix_promoter_prospects_promoter', 'promoter_prospects', ['promoter_user_id'])
    op.create_index('ix_promoter_prospects_email', 'promoter_prospects', ['contact_email'])
    op.create_table(
        'tenant_referrals',
        sa.Column('id', PK, primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.BigInteger(), sa.ForeignKey('tenants.id'), nullable=False, unique=True),
        sa.Column('promoter_user_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('prospect_id', sa.BigInteger(), sa.ForeignKey('promoter_prospects.id'), nullable=True),
        sa.Column('code', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_tenant_referrals_promoter', 'tenant_referrals', ['promoter_user_id'])

    # ---------------------------------------------------------------- catálogo
    op.create_table(
        'catalog_categories',
        sa.Column('id', PK, primary_key=True, autoincrement=True),
        sa.Column('parent_id', sa.BigInteger(), sa.ForeignKey('catalog_categories.id'), nullable=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('slug', sa.String(140), nullable=False, unique=True),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('is_inventory', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('requires_special_permits', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_catalog_categories_parent', 'catalog_categories', ['parent_id'])

    op.create_table(
        'providers',
        sa.Column('id', PK, primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.BigInteger(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('name', sa.String(180), nullable=False),
        sa.Column('contact_name', sa.String(180), nullable=True),
        sa.Column('contact_email', sa.String(254), nullable=True),
        sa.Column('phone', sa.String(40), nullable=True),
        sa.Column('notes', sa.String(1000), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_providers_tenant_id'),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_providers_tenant_name'),
        sa.CheckConstraint("status IN ('active','inactive')", name='ck_providers_status'),
    )

    op.create_table(
        'catalog_offers',
        sa.Column('id', PK, primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.BigInteger(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('provider_id', sa.BigInteger(), nullable=True),
        sa.Column('category_id', sa.BigInteger(), sa.ForeignKey('catalog_categories.id'), nullable=False),
        sa.Column('inventory_item_id', sa.BigInteger(), nullable=True),
        sa.Column('name', sa.String(180), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('pricing_mode', sa.String(20), nullable=False),
        sa.Column('unit_price', sa.Numeric(14, 2), nullable=True),
        sa.Column('fulfillment_type', sa.String(20), nullable=False),
        sa.Column('duration_hours', sa.Numeric(6, 2), nullable=True),
        sa.Column('min_guests', sa.Integer(), nullable=True),
        sa.Column('max_guests', sa.Integer(), nullable=True),
        sa.Column('coverage', sa.String(255), nullable=True),
        sa.Column('min_notice_days', sa.Integer(), nullable=True),
        sa.Column('setup_requirements', sa.String(1000), nullable=True),
        sa.Column('daily_capacity', sa.Integer(), nullable=True),
        sa.Column('requires_provider_confirmation', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('venue_restrictions', sa.String(1000), nullable=True),
        sa.Column('required_documents', sa.String(1000), nullable=True),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_catalog_offers_tenant_id'),
        sa.ForeignKeyConstraint(['tenant_id', 'provider_id'], ['providers.tenant_id', 'providers.id'],
                                name='fk_catalog_offers_provider_tenant'),
        sa.ForeignKeyConstraint(['tenant_id', 'inventory_item_id'],
                                ['inventory_items.tenant_id', 'inventory_items.id'],
                                name='fk_catalog_offers_inventory_tenant'),
        sa.CheckConstraint("status IN ('draft','published','archived')", name='ck_catalog_offers_status'),
        sa.CheckConstraint("pricing_mode IN ('unit','per_person','per_hour','package','per_event','quote')",
                           name='ck_catalog_offers_pricing_mode'),
        sa.CheckConstraint("fulfillment_type IN ('inventory','schedule','manual')",
                           name='ck_catalog_offers_fulfillment'),
        sa.CheckConstraint("unit_price IS NULL OR unit_price >= 0", name='ck_catalog_offers_price'),
        sa.CheckConstraint(
            "(fulfillment_type = 'inventory' AND inventory_item_id IS NOT NULL) "
            "OR (fulfillment_type <> 'inventory' AND inventory_item_id IS NULL)",
            name='ck_catalog_offers_inventory_link'),
    )
    op.create_index('ix_catalog_offers_tenant_category', 'catalog_offers', ['tenant_id', 'category_id'])
    op.create_index('ix_catalog_offers_tenant_status', 'catalog_offers', ['tenant_id', 'status'])

    # ------------------------------------------------ columnas en tablas existentes
    with op.batch_alter_table('quote_items') as batch:
        batch.add_column(sa.Column('offer_id', sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column('provider_id', sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column('category_id', sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column('pricing_mode', sa.String(20), nullable=True))
        batch.add_column(sa.Column('price_status', sa.String(20), nullable=False, server_default='confirmed'))
        batch.add_column(sa.Column('fulfillment_status', sa.String(30), nullable=False,
                                   server_default='not_required'))
        batch.add_column(sa.Column('compliance_status', sa.String(20), nullable=False,
                                   server_default='not_required'))
        batch.add_column(sa.Column('service_details', sa.JSON(), nullable=True))
        batch.create_foreign_key('fk_quote_items_offer_tenant', 'catalog_offers',
                                 ['tenant_id', 'offer_id'], ['tenant_id', 'id'])
        batch.create_foreign_key('fk_quote_items_provider_tenant', 'providers',
                                 ['tenant_id', 'provider_id'], ['tenant_id', 'id'])
        batch.create_foreign_key('fk_quote_items_category', 'catalog_categories', ['category_id'], ['id'])
        batch.create_check_constraint('ck_quote_items_price_status', "price_status IN ('confirmed', 'pending')")
        batch.create_check_constraint(
            'ck_quote_items_fulfillment_status',
            "fulfillment_status IN ('not_required', 'pending_confirmation', 'available', 'confirmed', "
            "'unavailable')")
        batch.create_check_constraint('ck_quote_items_compliance_status',
                                      "compliance_status IN ('not_required', 'pending', 'approved')")
        batch.create_index('ix_quote_items_tenant_provider', ['tenant_id', 'provider_id'])

    with op.batch_alter_table('memberships') as batch:
        batch.add_column(sa.Column('provider_id', sa.BigInteger(), nullable=True))
        batch.create_foreign_key('fk_membership_provider_same_tenant', 'providers',
                                 ['tenant_id', 'provider_id'], ['tenant_id', 'id'])
    with op.batch_alter_table('tenant_invitations') as batch:
        batch.add_column(sa.Column('provider_id', sa.BigInteger(), nullable=True))
        batch.create_foreign_key('fk_tenant_invitation_provider', 'providers',
                                 ['tenant_id', 'provider_id'], ['tenant_id', 'id'])

    # ------------------------------------------------------------------ datos
    conn = op.get_bind()
    now = _now()
    for order, (slug, name, is_inventory, special) in enumerate(CATEGORIES, start=1):
        if conn.execute(sa.text("SELECT id FROM catalog_categories WHERE slug = :slug"),
                        {"slug": slug}).scalar() is None:
            conn.execute(sa.text(
                "INSERT INTO catalog_categories (parent_id, name, slug, sort_order, is_active, is_inventory, "
                "requires_special_permits, created_at, updated_at) "
                "VALUES (NULL, :name, :slug, :sort_order, :active, :inv, :special, :now, :now)"),
                {"name": name, "slug": slug, "sort_order": order * 10, "active": True, "inv": is_inventory,
                 "special": special, "now": now})
    for code, role_names in NEW_PERMISSIONS.items():
        if conn.execute(sa.text("SELECT id FROM permissions WHERE code = :code"), {"code": code}).scalar() is None:
            conn.execute(sa.text("INSERT INTO permissions (code) VALUES (:code)"), {"code": code})
        conn.execute(sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = :code "
            "WHERE r.name IN :names AND NOT EXISTS ("
            "  SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
        ).bindparams(sa.bindparam("names", expanding=True)), {"code": code, "names": list(role_names)})


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM (SELECT id FROM permissions WHERE code IN "
        "('catalog.read', 'catalog.manage', 'provider.items')) AS p)"))
    with op.batch_alter_table('tenant_invitations') as batch:
        batch.drop_constraint('fk_tenant_invitation_provider', type_='foreignkey')
        batch.drop_column('provider_id')
    with op.batch_alter_table('memberships') as batch:
        batch.drop_constraint('fk_membership_provider_same_tenant', type_='foreignkey')
        batch.drop_column('provider_id')
    with op.batch_alter_table('quote_items') as batch:
        batch.drop_constraint('fk_quote_items_offer_tenant', type_='foreignkey')
        batch.drop_constraint('fk_quote_items_provider_tenant', type_='foreignkey')
        batch.drop_constraint('fk_quote_items_category', type_='foreignkey')
        batch.drop_constraint('ck_quote_items_price_status', type_='check')
        batch.drop_constraint('ck_quote_items_fulfillment_status', type_='check')
        batch.drop_constraint('ck_quote_items_compliance_status', type_='check')
        batch.drop_index('ix_quote_items_tenant_provider')
        for column in ('service_details', 'compliance_status', 'fulfillment_status', 'price_status',
                       'pricing_mode', 'category_id', 'provider_id', 'offer_id'):
            batch.drop_column(column)
    for table in ('catalog_offers', 'providers', 'catalog_categories', 'tenant_referrals',
                  'promoter_prospects', 'promoter_referral_codes', 'tenant_access_grants',
                  'audit_events', 'platform_invitations', 'platform_role_assignments'):
        op.drop_table(table)
