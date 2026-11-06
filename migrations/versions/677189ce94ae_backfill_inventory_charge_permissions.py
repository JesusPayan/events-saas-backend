"""backfill inventory charge permissions
Revision ID: 677189ce94ae
Revises: da4ad47a772d
"""
from alembic import op
import sqlalchemy as sa

revision = '677189ce94ae'
down_revision = 'da4ad47a772d'
branch_labels = None
depends_on = None


PERMISSION_CODES = (
    "inventory.charges.approve",
    "inventory.charges.pay",
)


def upgrade():
    bind = op.get_bind()

    # Crear únicamente los permisos faltantes.
    for code in PERMISSION_CODES:
        bind.execute(
            sa.text("""
                INSERT INTO permissions (code)
                SELECT :code
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM permissions
                    WHERE code = :code
                )
            """),
            {"code": code},
        )

    # Asignarlos a los roles owner existentes.
    # La PK compuesta evita duplicados.
    bind.execute(
        sa.text("""
            INSERT INTO role_permissions (
                role_id,
                permission_id
            )
            SELECT
                r.id,
                p.id
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.name = 'owner'
              AND p.code IN (
                  'inventory.charges.approve',
                  'inventory.charges.pay'
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM role_permissions rp
                  WHERE rp.role_id = r.id
                    AND rp.permission_id = p.id
              )
        """)
    )


def downgrade():
    # No eliminamos permisos compartidos ni
    # asignaciones que pudieran estar en uso.
    # Esta migración de datos es conservadora.
    pass
