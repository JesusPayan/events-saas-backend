
"""add incident charge lifecycle fields

Revision ID: da4ad47a772d
Revises: 75cb39d33f1b
"""

from alembic import op
import sqlalchemy as sa


revision = "da4ad47a772d"
down_revision = "75cb39d33f1b"
branch_labels = None
depends_on = None


TABLE_NAME = "inventory_incident_charges"
FK_NAME = "fk_incident_charges_waived_by"


def get_existing_columns():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    return {
        column["name"]
        for column in inspector.get_columns(TABLE_NAME)
    }


def get_existing_foreign_keys():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    return {
        fk["name"]
        for fk in inspector.get_foreign_keys(TABLE_NAME)
        if fk.get("name")
    }


def upgrade():
    columns = [
        sa.Column(
            "approved_at",
            sa.DateTime(),
            nullable=True
        ),
        sa.Column(
            "paid_at",
            sa.DateTime(),
            nullable=True
        ),
        sa.Column(
            "payment_reference",
            sa.String(length=120),
            nullable=True
        ),
        sa.Column(
            "payment_method",
            sa.String(length=30),
            nullable=True
        ),
        sa.Column(
            "waived_by",
            sa.BigInteger(),
            nullable=True
        ),
        sa.Column(
            "waived_at",
            sa.DateTime(),
            nullable=True
        ),
        sa.Column(
            "resolution_notes",
            sa.Text(),
            nullable=True
        ),
    ]

    existing_columns = get_existing_columns()

    for column in columns:
        if column.name not in existing_columns:
            op.add_column(TABLE_NAME, column)
            print(f"Columna creada: {column.name}")
        else:
            print(f"Columna existente: {column.name}")

    existing_fks = get_existing_foreign_keys()

    if FK_NAME not in existing_fks:
        op.create_foreign_key(
            FK_NAME,
            TABLE_NAME,
            "users",
            ["waived_by"],
            ["id"]
        )
        print(f"Foreign key creada: {FK_NAME}")
    else:
        print(f"Foreign key existente: {FK_NAME}")


def downgrade():
    existing_fks = get_existing_foreign_keys()

    if FK_NAME in existing_fks:
        op.drop_constraint(
            FK_NAME,
            TABLE_NAME,
            type_="foreignkey"
        )

    existing_columns = get_existing_columns()

    columns_to_remove = [
        "resolution_notes",
        "waived_at",
        "waived_by",
        "payment_method",
        "payment_reference",
        "paid_at",
        "approved_at",
    ]

    for column_name in columns_to_remove:
        if column_name in existing_columns:
            op.drop_column(TABLE_NAME, column_name)
            print(f"Columna eliminada: {column_name}")
