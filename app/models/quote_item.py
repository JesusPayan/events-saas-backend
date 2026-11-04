
from app.extensions import db
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint


class QuoteItem(db.Model):
    __tablename__ = "quote_items"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, nullable=False)
    quote_id = db.Column(db.BigInteger, nullable=False)

    item_type = db.Column(db.String(20), nullable=False)
    inventory_item_id = db.Column(db.BigInteger, nullable=True)

    description = db.Column(db.String(500), nullable=False)
    quantity = db.Column(db.Numeric(12, 2), nullable=False)
    unit_price = db.Column(db.Numeric(14, 2), nullable=False)

    discount_amount = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    tax_rate = db.Column(db.Numeric(7, 4), nullable=False, default=0)
    subtotal = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    tax_amount = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    sort_order = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "id",
            name="uq_quote_items_tenant_id",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "quote_id"],
            ["quotes.tenant_id", "quotes.id"],
            name="fk_quote_items_quote_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_quote_items_inventory_tenant",
        ),
        CheckConstraint(
            "quantity > 0",
            name="ck_quote_items_quantity_positive",
        ),
        CheckConstraint(
            "unit_price >= 0 AND discount_amount >= 0 "
            "AND subtotal >= 0 AND tax_amount >= 0 AND total >= 0",
            name="ck_quote_items_amounts_nonnegative",
        ),
        CheckConstraint(
            "tax_rate >= 0 AND tax_rate <= 1",
            name="ck_quote_items_tax_rate",
        ),
        CheckConstraint(
            "item_type IN ('inventory', 'service', 'custom')",
            name="ck_quote_items_type",
        ),
        CheckConstraint(
            "(item_type = 'inventory' AND inventory_item_id IS NOT NULL) "
            "OR (item_type <> 'inventory' AND inventory_item_id IS NULL)",
            name="ck_quote_items_inventory_type",
        ),
        db.Index("ix_quote_items_tenant_quote", "tenant_id", "quote_id"),
    )

    quote = db.relationship(
        "Quote",
        back_populates="items",
        foreign_keys=[tenant_id, quote_id],
    )
    db.CheckConstraint(
    'discount_amount <= subtotal',
    name='ck_quote_items_discount_limit'
)
