
from app.extensions import db
from sqlalchemy import ForeignKeyConstraint, CheckConstraint


class ContractItem(db.Model):
    __tablename__ = "contract_items"

    id = db.Column(
        db.BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    tenant_id = db.Column(db.BigInteger, nullable=False)
    contract_id = db.Column(db.BigInteger, nullable=False)

    description = db.Column(db.String(500), nullable=False)
    item_type = db.Column(db.String(30), nullable=False)

    quantity = db.Column(db.Numeric(12, 2), nullable=False)
    unit_price = db.Column(db.Numeric(14, 2), nullable=False)

    discount_amount = db.Column(
        db.Numeric(14, 2),
        nullable=False,
        default=0,
    )

    tax_rate = db.Column(
        db.Numeric(7, 4),
        nullable=False,
        default=0,
    )

    tax_amount = db.Column(
        db.Numeric(14, 2),
        nullable=False,
        default=0,
    )

    subtotal = db.Column(db.Numeric(14, 2), nullable=False)
    total = db.Column(db.Numeric(14, 2), nullable=False)

    sort_order = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "contract_id"],
            ["contracts.tenant_id", "contracts.id"],
            name="fk_contract_items_contract_tenant",
        ),
        CheckConstraint(
            "quantity > 0 AND unit_price >= 0",
            name="ck_contract_items_amounts",
        ),
        db.Index(
            "ix_contract_items_tenant_contract",
            "tenant_id",
            "contract_id",
        ),
    )
