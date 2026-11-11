
from datetime import datetime, timezone

from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class LogisticsOrder(db.Model):
    __tablename__ = "logistics_orders"

    id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )

    tenant_id = db.Column(db.BigInteger, nullable=False)
    event_id = db.Column(db.BigInteger, nullable=False)

    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending",
        server_default="pending",
    )

    scheduled_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.BigInteger, nullable=False)

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
    )
    
    # Información del despacho
    dispatched_at = db.Column(
        db.DateTime,
        nullable=True,
    )

    dispatched_by = db.Column(
        db.BigInteger,
        nullable=True,
    )

    dispatch_notes = db.Column(
        db.Text,
        nullable=True,
    )

    # Información de la entrega
    delivered_at = db.Column(
        db.DateTime,
        nullable=True,
    )

    delivered_by = db.Column(
        db.BigInteger,
        nullable=True,
    )

    delivery_notes = db.Column(
        db.Text,
        nullable=True,
    )

    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    items = db.relationship(
        "LogisticsOrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        db.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["events.tenant_id", "events.id"],
            name="fk_logistics_orders_event",
        ),
        db.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_logistics_orders_created_by",
        ),
        db.UniqueConstraint(
            "tenant_id", "id",
            name="uq_logistics_orders_tenant_id",
        ),
        db.CheckConstraint(
            "status IN ('pending', 'in_progress', "
            "'prepared', 'cancelled')",
            name="ck_logistics_orders_status",
        ),
        db.Index(
            "ix_logistics_orders_tenant_status",
            "tenant_id", "status",
        ),
        db.Index(
            "ix_logistics_orders_tenant_event",
            "tenant_id", "event_id",
        ),
        
        db.CheckConstraint(
            "status IN ("
            "'pending', "
            "'in_progress', "
            "'prepared', "
            "'dispatched', "
            "'delivered', "
            "'cancelled'"
            ")",
            name="ck_logistics_orders_status",
        ),
        
        db.ForeignKeyConstraint(
            ["dispatched_by"],
            ["users.id"],
            name="fk_logistics_orders_dispatched_by",
        ),
        db.ForeignKeyConstraint(
            ["delivered_by"],
            ["users.id"],
            name="fk_logistics_orders_delivered_by",
        ),


    )
