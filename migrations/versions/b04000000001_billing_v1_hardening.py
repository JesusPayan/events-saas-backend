"""BILL-04 v1.0 hardening: billing.manage permission, price audit, reconciliation issues.

Additive only: creates two tables and grants one new permission to existing
``owner`` roles. No existing row is updated or deleted.

Revision ID: b04000000001
Revises: b03000000001
"""
from alembic import op
import sqlalchemy as sa

revision = 'b04000000001'
down_revision = 'b03000000001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'billing_price_audits',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), primary_key=True, autoincrement=True),
        sa.Column('plan_id', sa.BigInteger(), sa.ForeignKey('billing_plans.id'), nullable=False),
        sa.Column('plan_price_id', sa.BigInteger(), sa.ForeignKey('billing_plan_prices.id'), nullable=False),
        sa.Column('previous_price_id', sa.BigInteger(), sa.ForeignKey('billing_plan_prices.id')),
        sa.Column('action', sa.String(30), nullable=False),
        sa.Column('old_amount', sa.Numeric(14, 2)),
        sa.Column('new_amount', sa.Numeric(14, 2)),
        sa.Column('actor_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("action IN ('reprice','activate','deactivate')", name='ck_billing_price_audit_action'),
    )
    op.create_index('ix_billing_price_audits_plan', 'billing_price_audits', ['plan_id', 'id'])

    op.create_table(
        'billing_mp_reconciliation_issues',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), primary_key=True, autoincrement=True),
        sa.Column('resource_type', sa.String(60), nullable=False),
        sa.Column('resource_id', sa.String(191), nullable=False),
        sa.Column('reason', sa.String(60), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('first_seen_at', sa.DateTime(), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(), nullable=False),
        sa.Column('resolved_at', sa.DateTime()),
        sa.UniqueConstraint('resource_type', 'resource_id', name='uq_mp_reconciliation_issue_resource'),
    )

    conn = op.get_bind()
    exists = conn.execute(sa.text("SELECT id FROM permissions WHERE code = 'billing.manage'")).scalar()
    if exists is None:
        conn.execute(sa.text("INSERT INTO permissions (code) VALUES ('billing.manage')"))
    # Grant to every existing tenant owner role, skipping roles that already have it.
    conn.execute(sa.text(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'billing.manage' "
        "WHERE r.name = 'owner' AND NOT EXISTS ("
        "  SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
    ))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM (SELECT id FROM permissions WHERE code = 'billing.manage') AS p)"
    ))
    op.drop_table('billing_mp_reconciliation_issues')
    op.drop_table('billing_price_audits')
