"""BILL-01.1 provider-neutral subscription foundation.

Revision ID: b11000000001
Revises: c03500000001
"""
from alembic import op
import sqlalchemy as sa

revision = "b11000000001"
down_revision = "c03500000001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("billing_plans",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(60), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table("billing_plan_prices",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("plan_id", sa.BigInteger(), sa.ForeignKey("billing_plans.id"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="MXN"),
        sa.Column("billing_interval", sa.String(12), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("plan_id", "currency", "billing_interval", "version", name="uq_billing_price_version"),
        sa.CheckConstraint("amount >= 0", name="ck_billing_price_nonnegative"),
        sa.CheckConstraint("billing_interval IN ('month', 'year')", name="ck_billing_price_interval"),
        sa.CheckConstraint("version > 0", name="ck_billing_price_version"),
    )
    op.create_table("billing_plan_entitlements",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("plan_id", sa.BigInteger(), sa.ForeignKey("billing_plans.id"), nullable=False),
        sa.Column("feature_code", sa.String(100), nullable=False),
        sa.Column("limit_value", sa.Integer()),
        sa.UniqueConstraint("plan_id", "feature_code", name="uq_billing_plan_feature"),
        sa.CheckConstraint("limit_value IS NULL OR limit_value >= 0", name="ck_billing_feature_limit"),
    )
    op.create_table("tenant_subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("plan_price_id", sa.BigInteger(), sa.ForeignKey("billing_plan_prices.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="trialing"),
        sa.Column("current_period_start", sa.DateTime()),
        sa.Column("current_period_end", sa.DateTime()),
        sa.Column("trial_ends_at", sa.DateTime()),
        sa.Column("canceled_at", sa.DateTime()),
        sa.Column("ended_at", sa.DateTime()),
        sa.Column("provider", sa.String(30)),
        sa.Column("provider_subscription_id", sa.String(191)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tenant_subscriptions_tenant_id"),
        sa.UniqueConstraint("provider", "provider_subscription_id", name="uq_subscription_provider_external"),
        sa.CheckConstraint("status IN ('incomplete','trialing','active','past_due','paused','canceled','expired')", name="ck_tenant_subscription_status"),
        sa.CheckConstraint("current_period_end IS NULL OR current_period_start IS NULL OR current_period_end > current_period_start", name="ck_tenant_subscription_period"),
    )
    op.create_index("ix_tenant_subscriptions_tenant_status", "tenant_subscriptions", ["tenant_id", "status"])
    op.create_table("subscription_audits",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("subscription_id", sa.BigInteger(), nullable=False),
        sa.Column("old_status", sa.String(20)),
        sa.Column("new_status", sa.String(20), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "subscription_id"], ["tenant_subscriptions.tenant_id", "tenant_subscriptions.id"], name="fk_subscription_audit_same_tenant"),
    )
    op.create_index("ix_subscription_audits_tenant_subscription", "subscription_audits", ["tenant_id", "subscription_id"])


def downgrade():
    op.drop_index("ix_subscription_audits_tenant_subscription", table_name="subscription_audits")
    op.drop_table("subscription_audits")
    op.drop_index("ix_tenant_subscriptions_tenant_status", table_name="tenant_subscriptions")
    op.drop_table("tenant_subscriptions")
    op.drop_table("billing_plan_entitlements")
    op.drop_table("billing_plan_prices")
    op.drop_table("billing_plans")
