"""AUTH-02: invitaciones de miembros y permiso members.manage.

Aditiva: crea tenant_invitations y otorga members.manage a los roles owner existentes.

Revision ID: b05000000001
Revises: b04000000001
"""
from alembic import op
import sqlalchemy as sa

revision = 'b05000000001'
down_revision = 'b04000000001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tenant_invitations',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.BigInteger(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('email', sa.String(254), nullable=False),
        sa.Column('role_key', sa.String(30), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('invited_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('accepted_user_id', sa.BigInteger(), sa.ForeignKey('users.id')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('accepted_at', sa.DateTime()),
        sa.CheckConstraint("status IN ('pending','accepted','revoked')", name='ck_tenant_invitation_status'),
    )
    op.create_index('ix_tenant_invitations_tenant_id', 'tenant_invitations', ['tenant_id'])
    op.create_index('ix_tenant_invitations_tenant_email', 'tenant_invitations', ['tenant_id', 'email'])

    conn = op.get_bind()
    if conn.execute(sa.text("SELECT id FROM permissions WHERE code = 'members.manage'")).scalar() is None:
        conn.execute(sa.text("INSERT INTO permissions (code) VALUES ('members.manage')"))
    conn.execute(sa.text(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'members.manage' "
        "WHERE r.name = 'owner' AND NOT EXISTS ("
        "  SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
    ))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM (SELECT id FROM permissions WHERE code = 'members.manage') AS p)"
    ))
    op.drop_table('tenant_invitations')
