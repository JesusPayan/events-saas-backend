
"""COM-03.1 create contract payments and audits

Revision ID: 8aae2f4fd6be
Revises: 6c0211000001
"""

from alembic import op
import sqlalchemy as sa

revision = "8aae2f4fd6be"
down_revision = "6c0211000001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contract_payments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("contract_id", sa.BigInteger(), nullable=False),
        sa.Column("payment_type", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("payment_method", sa.String(30), nullable=False),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("confirmed_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),

        sa.PrimaryKeyConstraint("id"),

        sa.UniqueConstraint(
            "tenant_id", "id",
            name="uq_contract_payments_tenant_id",
        ),
        sa.UniqueConstraint(
            "tenant_id", "contract_id", "reference",
            name="uq_contract_payments_reference",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contract_id"],
            ["contracts.tenant_id", "contracts.id"],
            name="fk_contract_payments_contract_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_contract_payments_created_by",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"],
            ["users.id"],
            name="fk_contract_payments_confirmed_by",
        ),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_contract_payments_positive_amount",
        ),
        sa.CheckConstraint(
            "payment_type IN ('advance', 'installment')",
            name="ck_contract_payments_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'cancelled')",
            name="ck_contract_payments_status",
        ),
    )

    op.create_index(
        "ix_contract_payments_tenant_contract_status",
        "contract_payments",
        ["tenant_id", "contract_id", "status"],
        unique=False,
    )

    op.create_table(
        "contract_payment_audits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("payment_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("previous_status", sa.String(20), nullable=True),
        sa.Column("new_status", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),

        sa.PrimaryKeyConstraint("id"),

        sa.ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            ["contract_payments.tenant_id", "contract_payments.id"],
            name="fk_contract_payment_audits_payment_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name="fk_contract_payment_audits_changed_by",
        ),
    )

    op.create_index(
        "ix_contract_payment_audits_tenant_payment",
        "contract_payment_audits",
        ["tenant_id", "payment_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_contract_payment_audits_tenant_payment",
        table_name="contract_payment_audits",
    )
    op.drop_table("contract_payment_audits")

    op.drop_index(
        "ix_contract_payments_tenant_contract_status",
        table_name="contract_payments",
    )
    op.drop_table("contract_payments")
