
from app.extensions import db
from app.models.logistics_order import utc_now


class LogisticsOrderItem(db.Model):
    __tablename__ = "logistics_order_items"

    id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )

    tenant_id = db.Column(db.BigInteger, nullable=False)
    logistics_order_id = db.Column(db.BigInteger, nullable=False)
    inventory_item_id = db.Column(db.BigInteger, nullable=False)

    quantity_required = db.Column(db.Integer, nullable=False)
    quantity_prepared = db.Column(
        db.Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    order = db.relationship(
        "LogisticsOrder",
        back_populates="items",
    )

    __table_args__ = (
        db.ForeignKeyConstraint(
            ["tenant_id", "logistics_order_id"],
            ["logistics_orders.tenant_id", "logistics_orders.id"],
            name="fk_logistics_items_order",
        ),
        db.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_logistics_items_inventory",
        ),
        db.UniqueConstraint(
            "tenant_id",
            "logistics_order_id",
            "inventory_item_id",
            name="uq_logistics_order_item",
        ),
        db.CheckConstraint(
            "quantity_required > 0",
            name="ck_logistics_quantity_required",
        ),
        db.CheckConstraint(
            "quantity_prepared >= 0 AND "
            "quantity_prepared <= quantity_required",
            name="ck_logistics_quantity_prepared",
        ),
        db.Index(
            "ix_logistics_items_tenant_order",
            "tenant_id", "logistics_order_id",
        ),
    )
