
"""COM-02.1 create contracts and contract items

Revision ID: 49decfb649f6
Revises: b7e504000001
"""

from alembic import op
import sqlalchemy as sa


revision = "49decfb649f6"
down_revision = "b7e504000001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contracts",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("quote_id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("contract_number", sa.String(40), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "currency",
            sa.String(3),
            nullable=False,
            server_default="MXN",
        ),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column("discount_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("tax_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("terms_conditions", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),

        sa.UniqueConstraint(
            "tenant_id", "id",
            name="uq_contracts_tenant_id",
        ),
        sa.UniqueConstraint(
            "tenant_id", "quote_id",
            name="uq_contracts_tenant_quote",
        ),
        sa.UniqueConstraint(
            "tenant_id", "contract_number",
            name="uq_contracts_tenant_number",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "quote_id"],
            ["quotes.tenant_id", "quotes.id"],
            name="fk_contracts_quote_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "client_id"],
            ["events.tenant_id", "events.id", "events.client_id"],
            name="fk_contracts_event_client_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_contracts_created_by",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'completed', 'cancelled')",
            name="ck_contracts_status",
        ),
        sa.CheckConstraint(
            "subtotal >= 0 AND discount_total >= 0 "
            "AND tax_total >= 0 AND total >= 0",
            name="ck_contracts_amounts",
        ),
    )

    op.create_index(
        "ix_contracts_tenant_status",
        "contracts",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_contracts_tenant_event",
        "contracts",
        ["tenant_id", "event_id"],
    )

    op.create_table(
        "contract_items",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("contract_id", sa.BigInteger(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("item_type", sa.String(30), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "discount_amount",
            sa.Numeric(14, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "tax_rate",
            sa.Numeric(7, 4),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "tax_amount",
            sa.Numeric(14, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),

        sa.ForeignKeyConstraint(
            ["tenant_id", "contract_id"],
            ["contracts.tenant_id", "contracts.id"],
            name="fk_contract_items_contract_tenant",
        ),
        sa.CheckConstraint(
            "quantity > 0 AND unit_price >= 0",
            name="ck_contract_items_amounts",
        ),
    )

    op.create_index(
        "ix_contract_items_tenant_contract",
        "contract_items",
        ["tenant_id", "contract_id"],
    )

    op.create_table(
        "contract_status_history",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("contract_id", sa.BigInteger(), nullable=False),
        sa.Column("previous_status", sa.String(20), nullable=True),
        sa.Column("new_status", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),

        sa.ForeignKeyConstraint(
            ["tenant_id", "contract_id"],
            ["contracts.tenant_id", "contracts.id"],
            name="fk_contract_history_contract_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name="fk_contract_history_changed_by",
        ),
    )

    op.create_index(
        "ix_contract_history_tenant_contract",
        "contract_status_history",
        ["tenant_id", "contract_id"],
    )


def downgrade():
    op.drop_index(
        "ix_contract_history_tenant_contract",
        table_name="contract_status_history",
    )
    op.drop_table("contract_status_history")

    op.drop_index(
        "ix_contract_items_tenant_contract",
        table_name="contract_items",
    )
    op.drop_table("contract_items")

    op.drop_index(
        "ix_contracts_tenant_event",
        table_name="contracts",
    )
    op.drop_index(
        "ix_contracts_tenant_status",
        table_name="contracts",
    )
    op.drop_table("contracts")
