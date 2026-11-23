"""BILL-01.1: provider-neutral subscription catalog and tenant subscription records."""
from datetime import datetime, timezone
from app.extensions import db
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class BillingPlan(db.Model):
    __tablename__ = "billing_plans"
    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True, autoincrement=True)
    code = db.Column(db.String(60), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)


class BillingPlanPrice(db.Model):
    __tablename__ = "billing_plan_prices"
    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True, autoincrement=True)
    plan_id = db.Column(db.BigInteger, db.ForeignKey("billing_plans.id"), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="MXN")
    billing_interval = db.Column(db.String(12), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint("plan_id", "currency", "billing_interval", "version", name="uq_billing_price_version"),
        CheckConstraint("amount >= 0", name="ck_billing_price_nonnegative"),
        CheckConstraint("billing_interval IN ('month', 'year')", name="ck_billing_price_interval"),
        CheckConstraint("version > 0", name="ck_billing_price_version"),
    )


class BillingPlanEntitlement(db.Model):
    __tablename__ = "billing_plan_entitlements"
    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True, autoincrement=True)
    plan_id = db.Column(db.BigInteger, db.ForeignKey("billing_plans.id"), nullable=False)
    feature_code = db.Column(db.String(100), nullable=False)
    limit_value = db.Column(db.Integer)  # NULL = unlimited; 0 = disabled
    __table_args__ = (
        UniqueConstraint("plan_id", "feature_code", name="uq_billing_plan_feature"),
        CheckConstraint("limit_value IS NULL OR limit_value >= 0", name="ck_billing_feature_limit"),
    )


class TenantSubscription(db.Model):
    __tablename__ = "tenant_subscriptions"
    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, db.ForeignKey("tenants.id"), nullable=False)
    plan_price_id = db.Column(db.BigInteger, db.ForeignKey("billing_plan_prices.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="trialing")
    current_period_start = db.Column(db.DateTime)
    current_period_end = db.Column(db.DateTime)
    trial_ends_at = db.Column(db.DateTime)
    canceled_at = db.Column(db.DateTime)
    ended_at = db.Column(db.DateTime)
    provider = db.Column(db.String(30))
    provider_subscription_id = db.Column(db.String(191))
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_tenant_subscriptions_tenant_id"),
        UniqueConstraint("provider", "provider_subscription_id", name="uq_subscription_provider_external"),
        CheckConstraint("status IN ('incomplete','trialing','active','past_due','paused','canceled','expired')", name="ck_tenant_subscription_status"),
        CheckConstraint("current_period_end IS NULL OR current_period_start IS NULL OR current_period_end > current_period_start", name="ck_tenant_subscription_period"),
        db.Index("ix_tenant_subscriptions_tenant_status", "tenant_id", "status"),
    )


class SubscriptionAudit(db.Model):
    __tablename__ = "subscription_audits"
    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, nullable=False)
    subscription_id = db.Column(db.BigInteger, nullable=False)
    old_status = db.Column(db.String(20))
    new_status = db.Column(db.String(20), nullable=False)
    action = db.Column(db.String(60), nullable=False)
    actor_id = db.Column(db.BigInteger, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "subscription_id"], ["tenant_subscriptions.tenant_id", "tenant_subscriptions.id"], name="fk_subscription_audit_same_tenant"),
        db.Index("ix_subscription_audits_tenant_subscription", "tenant_id", "subscription_id"),
    )


class BillingPriceAudit(db.Model):
    """Immutable record of every operator price change (who, when, old/new)."""
    __tablename__ = "billing_price_audits"
    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True, autoincrement=True)
    plan_id = db.Column(db.BigInteger, db.ForeignKey("billing_plans.id"), nullable=False)
    plan_price_id = db.Column(db.BigInteger, db.ForeignKey("billing_plan_prices.id"), nullable=False)
    previous_price_id = db.Column(db.BigInteger, db.ForeignKey("billing_plan_prices.id"))
    action = db.Column(db.String(30), nullable=False)
    old_amount = db.Column(db.Numeric(14, 2))
    new_amount = db.Column(db.Numeric(14, 2))
    actor_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (
        CheckConstraint("action IN ('reprice','activate','deactivate')", name="ck_billing_price_audit_action"),
        db.Index("ix_billing_price_audits_plan", "plan_id", "id"),
    )
