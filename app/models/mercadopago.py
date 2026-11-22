"""Durable checkout attempts, webhook deduplication and verified payment ledger."""
from app.extensions import db
from app.models.billing import utc_now

class MPCheckout(db.Model):
    __tablename__ = 'billing_mp_checkouts'
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.BigInteger, db.ForeignKey('tenants.id'), nullable=False, index=True)
    plan_price_id = db.Column(db.BigInteger, db.ForeignKey('billing_plan_prices.id'), nullable=False)
    payer_email = db.Column(db.String(254), nullable=False)
    external_reference = db.Column(db.String(100), unique=True, nullable=False)
    provider_subscription_id = db.Column(db.String(191), unique=True)
    status = db.Column(db.String(30), nullable=False, default='pending')
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

class MPWebhookEvent(db.Model):
    __tablename__ = 'billing_mp_webhook_events'
    id = db.Column(db.Integer, primary_key=True)
    event_key = db.Column(db.String(191), unique=True, nullable=False)
    resource_type = db.Column(db.String(60), nullable=False)
    resource_id = db.Column(db.String(191), nullable=False)
    received_at = db.Column(db.DateTime, nullable=False, default=utc_now)

class MPPayment(db.Model):
    __tablename__ = 'billing_mp_payments'
    id = db.Column(db.Integer, primary_key=True)
    provider_payment_id = db.Column(db.String(191), unique=True, nullable=False)
    provider_subscription_id = db.Column(db.String(191), nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False)
    amount = db.Column(db.Numeric(14,2), nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
