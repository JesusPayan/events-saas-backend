"""BILL-03 Mercado Pago checkout and payment tracking.
Revision ID: b03000000001
Revises: b11000000001
"""
from alembic import op
import sqlalchemy as sa
revision = 'b03000000001'
down_revision = 'b11000000001'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('billing_mp_checkouts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.BigInteger(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('plan_price_id', sa.BigInteger(), sa.ForeignKey('billing_plan_prices.id'), nullable=False),
        sa.Column('payer_email', sa.String(254), nullable=False),
        sa.Column('external_reference', sa.String(100), nullable=False, unique=True),
        sa.Column('provider_subscription_id', sa.String(191), unique=True),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_billing_mp_checkouts_tenant_id', 'billing_mp_checkouts', ['tenant_id'])
    op.create_table('billing_mp_webhook_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('event_key', sa.String(191), nullable=False, unique=True),
        sa.Column('resource_type', sa.String(60), nullable=False),
        sa.Column('resource_id', sa.String(191), nullable=False),
        sa.Column('received_at', sa.DateTime(), nullable=False))
    op.create_table('billing_mp_payments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('provider_payment_id', sa.String(191), nullable=False, unique=True),
        sa.Column('provider_subscription_id', sa.String(191), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('amount', sa.Numeric(14,2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_billing_mp_payments_provider_subscription_id', 'billing_mp_payments', ['provider_subscription_id'])

def downgrade():
    op.drop_index('ix_billing_mp_payments_provider_subscription_id', table_name='billing_mp_payments')
    op.drop_table('billing_mp_payments')
    op.drop_table('billing_mp_webhook_events')
    op.drop_index('ix_billing_mp_checkouts_tenant_id', table_name='billing_mp_checkouts')
    op.drop_table('billing_mp_checkouts')
