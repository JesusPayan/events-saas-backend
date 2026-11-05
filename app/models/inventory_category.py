
from app.extensions import db


class InventoryCategory(db.Model):
    __tablename__ = "inventory_categories"

    id = db.Column(
    db.BigInteger().with_variant(db.Integer, "sqlite"),
    primary_key=True,
    autoincrement=True
    )

    tenant_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey("tenants.id"),
        nullable=False,
        index=True
    )

    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255))
    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_inventory_category_tenant_name"
        ),
        db.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_inventory_category_tenant_id"
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_active": self.is_active
        }
