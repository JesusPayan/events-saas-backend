
"""fix inventory incident charge missing fields

Revision ID: 29eafe22476c
Revises: 75cb39d33f1b
"""

from alembic import op
import sqlalchemy as sa

revision = "29eafe22476c"
down_revision = "75cb39d33f1b"
branch_labels = None
depends_on = None

TABLE = "inventory_incident_charges"
FK_NAME = "fk_incident_charge_waived_by"

COLUMNS = [
    ("approved_at", sa.DateTime()),
    ("paid_at", sa.DateTime()),
    ("payment_reference", sa.String(120)),
    ("payment_method", sa.String(30)),
    ("waived_by", sa.BigInteger()),
    ("waived_at", sa.DateTime()),
    ("resolution_notes", sa.Text()),
]


def existing_columns():
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(TABLE)
    }


def waived_by_foreign_keys():
    return [
        fk for fk in sa.inspect(op.get_bind()).get_foreign_keys(TABLE)
        if fk.get("referred_table") == "users"
        and fk.get("constrained_columns") == ["waived_by"]
        and fk.get("referred_columns") == ["id"]
    ]


def upgrade():
    columns = existing_columns()

    for name, column_type in COLUMNS:
        if name not in columns:
            op.add_column(
                TABLE,
                sa.Column(name, column_type, nullable=True),
            )

    if not waived_by_foreign_keys():
        op.create_foreign_key(
            FK_NAME,
            TABLE,
            "users",
            ["waived_by"],
            ["id"],
        )


def downgrade():
    # No eliminar columnas compartidas con la otra rama.
    # La reversión de esta revisión requiere una estrategia
    # específica según las revisiones aplicadas.
    raise RuntimeError(
        "Downgrade de 29eafe22476c no soportado "
        "sin reconciliar las ramas de migraciones."
    )
