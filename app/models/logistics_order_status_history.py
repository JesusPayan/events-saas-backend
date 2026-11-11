
from app.extensions import db
from app.models.logistics_order import utc_now


class LogisticsOrderStatusHistory(db.Model):
    __tablename__ = "logistics_order_status_history"

    id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )

    tenant_id = db.Column(
        db.BigInteger,
        nullable=False,
    )

    logistics_order_id = db.Column(
        db.BigInteger,
        nullable=False,
    )

    previous_status = db.Column(
        db.String(20),
        nullable=True,
    )

    new_status = db.Column(
        db.String(20),
        nullable=False,
    )

    changed_by = db.Column(
        db.BigInteger,
        nullable=False,
    )

    notes = db.Column(
        db.Text,
        nullable=True,
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
    )

    __table_args__ = (
        db.ForeignKeyConstraint(
            ["tenant_id", "logistics_order_id"],
            ["logistics_orders.tenant_id", "logistics_orders.id"],
            name="fk_logistics_history_order",
        ),
        db.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name="fk_logistics_history_user",
        ),
        db.Index(
            "ix_logistics_history_tenant_order",
            "tenant_id",
            "logistics_order_id",
        ),
    )
