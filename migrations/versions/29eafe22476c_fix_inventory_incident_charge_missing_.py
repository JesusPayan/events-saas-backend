"""fix inventory incident charge missing fields
Revision ID: 29eafe22476c
Revises: 75cb39d33f1b
"""
from alembic import op
import sqlalchemy as sa




revision = '29eafe22476c'
down_revision = "75cb39d33f1b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "inventory_incident_charges",
        sa.Column(
            "approved_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    op.add_column(
        "inventory_incident_charges",
        sa.Column(
            "paid_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    op.add_column(
        "inventory_incident_charges",
        sa.Column(
            "payment_reference",
            sa.String(length=120),
            nullable=True,
        ),
    )

    op.add_column(
        "inventory_incident_charges",
        sa.Column(
            "payment_method",
            sa.String(length=30),
            nullable=True,
        ),
    )

    op.add_column(
        "inventory_incident_charges",
        sa.Column(
            "waived_by",
            sa.BigInteger(),
            nullable=True,
        ),
    )

    op.add_column(
        "inventory_incident_charges",
        sa.Column(
            "waived_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    op.add_column(
        "inventory_incident_charges",
        sa.Column(
            "resolution_notes",
            sa.Text(),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "fk_incident_charge_waived_by",
        "inventory_incident_charges",
        "users",
        ["waived_by"],
        ["id"],
    )


def downgrade():
    op.drop_constraint(
        "fk_incident_charge_waived_by",
        "inventory_incident_charges",
        type_="foreignkey",
    )

    op.drop_column(
        "inventory_incident_charges",
        "resolution_notes",
    )

    op.drop_column(
        "inventory_incident_charges",
        "waived_at",
    )

    op.drop_column(
        "inventory_incident_charges",
        "waived_by",
    )

    op.drop_column(
        "inventory_incident_charges",
        "payment_method",
    )

    op.drop_column(
        "inventory_incident_charges",
        "payment_reference",
    )

    op.drop_column(
        "inventory_incident_charges",
        "paid_at",
    )

    op.drop_column(
        "inventory_incident_charges",
        "approved_at",
    )
