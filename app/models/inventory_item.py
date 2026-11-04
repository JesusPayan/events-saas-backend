
from datetime import datetime, timezone
from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InventoryItem(db.Model):
    __tablename__ = "inventory_items"

    id = db.Column(
        db.BigInteger,
        primary_key=True,
        autoincrement=True
    )

    tenant_id = db.Column(
        db.BigInteger,
        db.ForeignKey("tenants.id"),
        nullable=False,
        index=True
    )

    category_id = db.Column(
        db.BigInteger,
        nullable=True
    )

    sku = db.Column(db.String(60), nullable=False)
    name = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text)

    item_type = db.Column(
        db.String(20),
        nullable=False,
        default="product"
    )

    quantity_total = db.Column(
        db.Integer,
        nullable=False,
        default=0
    )

    unit = db.Column(
        db.String(30),
        nullable=False,
        default="piece"
    )

    replacement_cost = db.Column(db.Numeric(12, 2))
    rental_price = db.Column(db.Numeric(12, 2))

    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now
    )

    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now
    )
    quantity_unavailable = db.Column(
    db.Integer,
    nullable=False,
    default=0,
    server_default="0"
)

    __table_args__ = (
        db.CheckConstraint(
    "quantity_unavailable >= 0",
    name="ck_inventory_unavailable_nonnegative"
),
db.CheckConstraint(
    "quantity_unavailable <= quantity_total",
    name="ck_inventory_unavailable_within_total"
),
        db.UniqueConstraint(
            "tenant_id",
            "sku",
            name="uq_inventory_item_tenant_sku"
        ),
        db.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_inventory_item_tenant_id"
        ),
        db.ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            [
                "inventory_categories.tenant_id",
                "inventory_categories.id"
            ],
            name="fk_inventory_item_category_tenant"
        ),
        db.CheckConstraint(
            "quantity_total >= 0",
            name="ck_inventory_quantity_nonnegative"
        ),
    )
    @property
    def quantity_rentable(self):
        return (
            self.quantity_total
            - self.quantity_unavailable
        )

    def to_dict(self):
        return {
            "id": self.id,
            "category_id": self.category_id,
            "sku": self.sku,
            "name": self.name,
            "description": self.description,
            "item_type": self.item_type,
            "quantity_total": self.quantity_total,
            "unit": self.unit,
            "replacement_cost": (
                str(self.replacement_cost)
                if self.replacement_cost is not None else None
            ),
            "rental_price": (
                str(self.rental_price)
                if self.rental_price is not None else None
            ),
            "is_active": self.is_active,
            "created_at": (
                self.created_at.isoformat() + "Z"
                if self.created_at else None
            ),
            "quantity_unavailable": self.quantity_unavailable,
                "quantity_rentable": self.quantity_rentable,
        }
