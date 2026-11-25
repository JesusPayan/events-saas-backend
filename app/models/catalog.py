"""CAT-01: catálogo de productos y servicios para eventos.

- ``catalog_categories``: categorías globales administrables, con subcategorías
  (``parent_id``). Se agregan desde el panel de plataforma sin publicar versión.
- ``providers``: proveedores registrados por cada organización (subcontratistas).
  Una oferta sin proveedor pertenece a la propia organización.
- ``catalog_offers``: servicios u ofertas de cada organización con modalidad de
  precio. El mobiliario existente sigue en ``inventory_items`` y se presenta en el
  catálogo bajo «Renta de mobiliario» sin migrar sus datos.
"""
from app.extensions import db
from app.models.identity import now

_PK = db.BigInteger().with_variant(db.Integer, "sqlite")

PRICING_MODES = ("unit", "per_person", "per_hour", "package", "per_event", "quote")
FULFILLMENT_TYPES = ("inventory", "schedule", "manual")
OFFER_STATUSES = ("draft", "published", "archived")


class CatalogCategory(db.Model):
    __tablename__ = "catalog_categories"
    id = db.Column(_PK, primary_key=True, autoincrement=True)
    parent_id = db.Column(db.BigInteger, db.ForeignKey("catalog_categories.id"), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(140), nullable=False, unique=True)
    description = db.Column(db.String(500), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # Ofertas que consumen inventario físico (mobiliario).
    is_inventory = db.Column(db.Boolean, nullable=False, default=False)
    # Pirotecnia y efectos especiales: restricciones del recinto, documentos y confirmación.
    requires_special_permits = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    updated_at = db.Column(db.DateTime, nullable=False, default=now, onupdate=now)
    __table_args__ = (db.Index("ix_catalog_categories_parent", "parent_id"),)


class Provider(db.Model):
    __tablename__ = "providers"
    id = db.Column(_PK, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, db.ForeignKey("tenants.id"), nullable=False)
    name = db.Column(db.String(180), nullable=False)
    contact_name = db.Column(db.String(180), nullable=True)
    contact_email = db.Column(db.String(254), nullable=True)
    phone = db.Column(db.String(40), nullable=True)
    notes = db.Column(db.String(1000), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="active")
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    updated_at = db.Column(db.DateTime, nullable=False, default=now, onupdate=now)
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "id", name="uq_providers_tenant_id"),
        db.UniqueConstraint("tenant_id", "name", name="uq_providers_tenant_name"),
        db.CheckConstraint("status IN ('active','inactive')", name="ck_providers_status"),
    )


class CatalogOffer(db.Model):
    __tablename__ = "catalog_offers"
    id = db.Column(_PK, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, db.ForeignKey("tenants.id"), nullable=False)
    provider_id = db.Column(db.BigInteger, nullable=True)
    category_id = db.Column(db.BigInteger, db.ForeignKey("catalog_categories.id"), nullable=False)
    inventory_item_id = db.Column(db.BigInteger, nullable=True)
    name = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="draft")
    pricing_mode = db.Column(db.String(20), nullable=False)
    unit_price = db.Column(db.Numeric(14, 2), nullable=True)
    fulfillment_type = db.Column(db.String(20), nullable=False)
    # Datos de servicio (opcionales según la categoría).
    duration_hours = db.Column(db.Numeric(6, 2), nullable=True)
    min_guests = db.Column(db.Integer, nullable=True)
    max_guests = db.Column(db.Integer, nullable=True)
    coverage = db.Column(db.String(255), nullable=True)
    min_notice_days = db.Column(db.Integer, nullable=True)
    setup_requirements = db.Column(db.String(1000), nullable=True)
    # Eventos que el proveedor puede atender por día; NULL = confirmación manual.
    daily_capacity = db.Column(db.Integer, nullable=True)
    requires_provider_confirmation = db.Column(db.Boolean, nullable=False, default=False)
    venue_restrictions = db.Column(db.String(1000), nullable=True)
    required_documents = db.Column(db.String(1000), nullable=True)
    created_by = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    updated_at = db.Column(db.DateTime, nullable=False, default=now, onupdate=now)
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "id", name="uq_catalog_offers_tenant_id"),
        db.ForeignKeyConstraint(["tenant_id", "provider_id"], ["providers.tenant_id", "providers.id"],
                                name="fk_catalog_offers_provider_tenant"),
        db.ForeignKeyConstraint(["tenant_id", "inventory_item_id"],
                                ["inventory_items.tenant_id", "inventory_items.id"],
                                name="fk_catalog_offers_inventory_tenant"),
        db.CheckConstraint("status IN ('draft','published','archived')", name="ck_catalog_offers_status"),
        db.CheckConstraint(
            "pricing_mode IN ('unit','per_person','per_hour','package','per_event','quote')",
            name="ck_catalog_offers_pricing_mode"),
        db.CheckConstraint("fulfillment_type IN ('inventory','schedule','manual')",
                           name="ck_catalog_offers_fulfillment"),
        db.CheckConstraint("unit_price IS NULL OR unit_price >= 0", name="ck_catalog_offers_price"),
        db.CheckConstraint(
            "(fulfillment_type = 'inventory' AND inventory_item_id IS NOT NULL) "
            "OR (fulfillment_type <> 'inventory' AND inventory_item_id IS NULL)",
            name="ck_catalog_offers_inventory_link"),
        db.Index("ix_catalog_offers_tenant_category", "tenant_id", "category_id"),
        db.Index("ix_catalog_offers_tenant_status", "tenant_id", "status"),
    )
