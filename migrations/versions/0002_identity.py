"""Identity, roles and memberships.
Revision ID: 0002_identity
Revises: 0001_create_tenants
"""
from alembic import op
import sqlalchemy as sa
revision = '0002_identity'
down_revision = '0001_create_tenants'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('users', sa.Column('id',sa.BigInteger(),primary_key=True,autoincrement=True),sa.Column('email',sa.String(254),nullable=False),sa.Column('password_hash',sa.String(255),nullable=False),sa.Column('is_active',sa.Boolean(),nullable=False),sa.Column('created_at',sa.DateTime(),nullable=False),sa.UniqueConstraint('email'))
    op.create_table('roles',sa.Column('id',sa.BigInteger(),primary_key=True,autoincrement=True),sa.Column('tenant_id',sa.BigInteger(),sa.ForeignKey('tenants.id'),nullable=False),sa.Column('name',sa.String(60),nullable=False),sa.UniqueConstraint('tenant_id','name'),sa.UniqueConstraint('tenant_id','id'))
    op.create_table('permissions',sa.Column('id',sa.BigInteger(),primary_key=True,autoincrement=True),sa.Column('code',sa.String(100),nullable=False),sa.UniqueConstraint('code'))
    op.create_table('role_permissions',sa.Column('role_id',sa.BigInteger(),sa.ForeignKey('roles.id',ondelete='CASCADE'),primary_key=True),sa.Column('permission_id',sa.BigInteger(),sa.ForeignKey('permissions.id',ondelete='CASCADE'),primary_key=True))
    op.create_table('memberships',sa.Column('id',sa.BigInteger(),primary_key=True,autoincrement=True),sa.Column('tenant_id',sa.BigInteger(),sa.ForeignKey('tenants.id'),nullable=False),sa.Column('user_id',sa.BigInteger(),sa.ForeignKey('users.id'),nullable=False),sa.Column('role_id',sa.BigInteger(),nullable=False),sa.Column('status',sa.String(20),nullable=False),sa.ForeignKeyConstraint(['tenant_id','role_id'],['roles.tenant_id','roles.id']),sa.UniqueConstraint('tenant_id','user_id'))

def downgrade():
    for table in ('memberships','role_permissions','permissions','roles','users'):
        op.drop_table(table)
