
"""inventory charge approvals and audit

Revision ID: 379533853b76
Revises: f3dd57d05ff3
"""

from alembic import op
import sqlalchemy as sa


revision = "379533853b76"
down_revision = "f3dd57d05ff3"
branch_labels = None
depends_on = None


def upgrade():

    # 1. Índice para la clave foránea compuesta
    op.create_index(
        "ix_incident_charges_tenant_id",
        "inventory_incident_charges",
        ["tenant_id", "id"],
        unique=True
    )

    # 2. Agregar usuario aprobador
    op.add_column(
        "inventory_incident_charges",
        sa.Column(
            "approved_by",
            sa.BigInteger(),
            nullable=True
        )
    )

    # 3. Relación con usuario aprobador
    op.create_foreign_key(
        "fk_incident_charge_approved_by",
        "inventory_incident_charges",
        "users",
        ["approved_by"],
        ["id"]
    )

    # 4. Crear tabla de auditoría
    op.create_table(
        "inventory_charge_audits",

        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True
        ),

        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            nullable=False
        ),

        sa.Column(
            "charge_id",
            sa.BigInteger(),
            nullable=False
        ),

        sa.Column(
            "previous_status",
            sa.String(20),
            nullable=False
        ),

        sa.Column(
            "new_status",
            sa.String(20),
            nullable=False
        ),

        sa.Column(
            "notes",
            sa.Text(),
            nullable=True
        ),

        sa.Column(
            "changed_by",
            sa.BigInteger(),
            nullable=False
        ),

        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False
        ),

        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_charge_audit_tenant_id"
        ),

        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name="fk_charge_audit_changed_by"
        ),

        sa.ForeignKeyConstraint(
            ["tenant_id", "charge_id"],
            [
                "inventory_incident_charges.tenant_id",
                "inventory_incident_charges.id"
            ],
            name="fk_charge_audit_tenant"
        )
    )

    # 5. Índice de consultas de auditoría
    op.create_index(
        "ix_charge_audit_tenant_charge",
        "inventory_charge_audits",
        ["tenant_id", "charge_id"],
        unique=False
    )


def downgrade():

    # 1. Eliminar índice de auditoría
    op.drop_index(
        "ix_charge_audit_tenant_charge",
        table_name="inventory_charge_audits"
    )

    # 2. Eliminar tabla de auditoría
    op.drop_table(
        "inventory_charge_audits"
    )

    # 3. Eliminar FK de aprobador
    op.drop_constraint(
        "fk_incident_charge_approved_by",
        "inventory_incident_charges",
        type_="foreignkey"
    )

    # 4. Eliminar columna
    op.drop_column(
        "inventory_incident_charges",
        "approved_by"
    )

    # 5. Eliminar índice compuesto
    op.drop_index(
        "ix_incident_charges_tenant_id",
        table_name="inventory_incident_charges"
    )
