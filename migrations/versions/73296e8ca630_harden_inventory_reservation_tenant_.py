"""harden inventory reservation tenant constraints
Revision ID: 73296e8ca630
Revises: bf22df0d8a9d
"""
from alembic import op
import sqlalchemy as sa

revision = '73296e8ca630'
down_revision = 'bf22df0d8a9d'
branch_labels = None
depends_on = None


# Conserva revision, down_revision,
# branch_labels y depends_on generados por Alembic.

RESERVATIONS = "inventory_reservations"
CHARGES = "inventory_incident_charges"

FK_EVENT = "fk_reservation_event_tenant"
FK_ITEM = "fk_reservation_item_tenant"

FK_OLD = "fk_incident_charge_waived_by"
FK_KEEP = "fk_incident_charges_waived_by"


def foreign_keys(table):
    return sa.inspect(op.get_bind()).get_foreign_keys(table)


def has_fk(table, name):
    return any(
        fk["name"] == name
        for fk in foreign_keys(table)
    )


def validate_reservations():
    bind = op.get_bind()

    invalid = bind.execute(sa.text("""
        SELECT COUNT(*)
        FROM inventory_reservations r
        LEFT JOIN events e
          ON e.id = r.event_id
        LEFT JOIN inventory_items i
          ON i.id = r.inventory_item_id
        WHERE e.id IS NULL
           OR i.id IS NULL
           OR NOT (r.tenant_id <=> e.tenant_id)
           OR NOT (r.tenant_id <=> i.tenant_id)
    """)).scalar_one()

    if invalid:
        raise RuntimeError(
            f"Existen {invalid} reservas con "
            "referencias de tenant inconsistentes"
        )


def upgrade():
    validate_reservations()

    if not has_fk(RESERVATIONS, FK_EVENT):
        op.create_foreign_key(
            FK_EVENT,
            RESERVATIONS,
            "events",
            ["tenant_id", "event_id"],
            ["tenant_id", "id"],
        )

    if not has_fk(RESERVATIONS, FK_ITEM):
        op.create_foreign_key(
            FK_ITEM,
            RESERVATIONS,
            "inventory_items",
            ["tenant_id", "inventory_item_id"],
            ["tenant_id", "id"],
        )

    if has_fk(CHARGES, FK_OLD):
        if not has_fk(CHARGES, FK_KEEP):
            raise RuntimeError(
                "No existe la FK alternativa de waived_by"
            )

        op.drop_constraint(
            FK_OLD,
            CHARGES,
            type_="foreignkey",
        )


def downgrade():
    # Restaurar la FK anterior solo si falta
    # y si no existe otra equivalente.
    waiver_fks = [
        fk for fk in foreign_keys(CHARGES)
        if fk.get("constrained_columns") == ["waived_by"]
        and fk.get("referred_table") == "users"
        and fk.get("referred_columns") == ["id"]
    ]

    if not waiver_fks:
        op.create_foreign_key(
            FK_OLD,
            CHARGES,
            "users",
            ["waived_by"],
            ["id"],
        )

    if has_fk(RESERVATIONS, FK_ITEM):
        op.drop_constraint(
            FK_ITEM,
            RESERVATIONS,
            type_="foreignkey",
        )

    if has_fk(RESERVATIONS, FK_EVENT):
        op.drop_constraint(
            FK_EVENT,
            RESERVATIONS,
            type_="foreignkey",
        )
