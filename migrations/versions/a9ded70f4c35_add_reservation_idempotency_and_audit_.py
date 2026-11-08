
"""add reservation idempotency and audit tables

Revision ID: a9ded70f4c35
Revises: 73296e8ca630
"""

from alembic import op
import sqlalchemy as sa


revision = "a9ded70f4c35"
down_revision = "73296e8ca630"
branch_labels = None
depends_on = None


def upgrade():

    # =====================================================
    # 1. TABLA DE IDEMPOTENCIA
    # =====================================================

    op.create_table(
        "api_idempotency_keys",

        sa.Column(
            "id",
            sa.BigInteger().with_variant(
                sa.Integer(), "sqlite"
            ),
            primary_key=True,
            autoincrement=True,
        ),

        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            nullable=False,
        ),

        sa.Column(
            "operation",
            sa.String(length=100),
            nullable=False,
        ),

        sa.Column(
            "idempotency_key",
            sa.String(length=128),
            nullable=False,
        ),

        sa.Column(
            "request_hash",
            sa.String(length=64),
            nullable=False,
        ),

        sa.Column(
            "response_status",
            sa.Integer(),
            nullable=True,
        ),

        sa.Column(
            "response_body",
            sa.JSON(),
            nullable=True,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),

        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),

        sa.UniqueConstraint(
            "tenant_id",
            "operation",
            "idempotency_key",
            name="uq_api_idempotency_tenant_operation_key",
        ),
    )

    op.create_index(
        "ix_api_idempotency_tenant_created",
        "api_idempotency_keys",
        ["tenant_id", "created_at"],
        unique=False,
    )

    # =====================================================
    # 2. TABLA DE AUDITORÍA DE RESERVAS
    # =====================================================

    op.create_table(
        "inventory_reservation_audits",

        sa.Column(
            "id",
            sa.BigInteger().with_variant(
                sa.Integer(), "sqlite"
            ),
            primary_key=True,
            autoincrement=True,
        ),

        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            nullable=False,
        ),

        sa.Column(
            "reservation_id",
            sa.BigInteger(),
            nullable=False,
        ),

        sa.Column(
            "action",
            sa.String(length=30),
            nullable=False,
        ),

        sa.Column(
            "previous_quantity",
            sa.Integer(),
            nullable=True,
        ),

        sa.Column(
            "new_quantity",
            sa.Integer(),
            nullable=True,
        ),

        sa.Column(
            "previous_status",
            sa.String(length=20),
            nullable=True,
        ),

        sa.Column(
            "new_status",
            sa.String(length=20),
            nullable=False,
        ),

        sa.Column(
            "changed_by",
            sa.BigInteger(),
            nullable=False,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),

        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
        ),

        sa.ForeignKeyConstraint(
            ["tenant_id", "reservation_id"],
            [
                "inventory_reservations.tenant_id",
                "inventory_reservations.id",
            ],
            name="fk_reservation_audit_tenant",
        ),
    )

    op.create_index(
        "ix_reservation_audit_tenant_reservation",
        "inventory_reservation_audits",
        ["tenant_id", "reservation_id"],
        unique=False,
    )


def downgrade():

    # =====================================================
    # REVERTIR SOLO LOS CAMBIOS DE ESTA MIGRACIÓN
    # =====================================================

    op.drop_index(
        "ix_reservation_audit_tenant_reservation",
        table_name="inventory_reservation_audits",
    )

    op.drop_table(
        "inventory_reservation_audits"
    )

    op.drop_index(
        "ix_api_idempotency_tenant_created",
        table_name="api_idempotency_keys",
    )

    op.drop_table(
        "api_idempotency_keys"
    )
