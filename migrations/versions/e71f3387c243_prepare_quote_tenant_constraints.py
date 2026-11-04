"""prepare quote tenant constraints
Revision ID: e71f3387c243
Revises: 4815532a5b29
"""
from alembic import op
import sqlalchemy as sa

revision = 'e71f3387c243'
down_revision = '4815532a5b29'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()

    # Validar integridad entre eventos y clientes.
    invalid_events = bind.execute(
        sa.text("""
            SELECT COUNT(*)
            FROM events e
            LEFT JOIN clients c
                ON c.id = e.client_id
            WHERE c.id IS NULL
               OR e.tenant_id <> c.tenant_id
        """)
    ).scalar_one()

    if invalid_events:
        raise RuntimeError(
            f"Se encontraron {invalid_events} eventos "
            "con clientes de otra empresa."
        )

    # Permitir referencias compuestas por tenant.
    op.create_unique_constraint(
        "uq_clients_tenant_id",
        "clients",
        ["tenant_id", "id"]
    )

    op.create_unique_constraint(
        "uq_events_tenant_id",
        "events",
        ["tenant_id", "id"]
    )

    # Garantizar que la cotización se vincule
    # al cliente correcto del evento.
    op.create_unique_constraint(
        "uq_events_tenant_id_client",
        "events",
        ["tenant_id", "id", "client_id"]
    )


def downgrade():
    op.drop_constraint(
        "uq_events_tenant_id_client",
        "events",
        type_="unique"
    )

    op.drop_constraint(
        "uq_events_tenant_id",
        "events",
        type_="unique"
    )

    op.drop_constraint(
        "uq_clients_tenant_id",
        "clients",
        type_="unique"
    )
