"""COM-03.2 backfill commercial owner permissions
Revision ID: 9bb5c58fb617
Revises: 8aae2f4fd6be
"""
from alembic import op
import sqlalchemy as sa

revision = '9bb5c58fb617'
down_revision = '8aae2f4fd6be'
branch_labels = None
depends_on = None
COMMERCIAL_PERMISSIONS = (
    "quotes.create",
    "quotes.read",
    "contracts.create",
    "contracts.read",
    "contracts.update",
)

def upgrade():
    connection = op.get_bind()

    for code in COMMERCIAL_PERMISSIONS:
        connection.execute(
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

    connection.execute(
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
                  'quotes.create',
                  'quotes.read',
                  'contracts.create',
                  'contracts.read',
                  'contracts.update'
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
    pass
