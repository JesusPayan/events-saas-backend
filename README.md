# BILL-01.1 — Backend patch

Copy `app/models/billing.py` and `app/migrations/versions/b11000000001_bill_01_1_billing_core.py` into the corresponding backend paths. The supplied ZIP originally flattens `app/` into its root; the paths here refer to your **real** backend repository where `app/` is the Python package.

**Important:** add `from app.models.billing import BillingPlan, BillingPlanPrice, BillingPlanEntitlement, TenantSubscription, SubscriptionAudit  # noqa: F401` in `app/__init__.py` alongside existing model imports, so SQLAlchemy metadata discovers the tables. Do not edit the provided source ZIP.

Before migration, run `python -m flask --app app:create_app db heads` and `python -m flask --app app:create_app db current` using `FLASK_ENV=test` and a database URL pointing to `crm_events_test`. The patch's `down_revision=c03500000001` assumes the provided ZIP reflects the latest `development` migration chain. If `db heads` shows another revision, **stop** and reconcile before upgrading.

After confirming the migration chain, run `python -m flask --app app:create_app db upgrade` against `crm_events_test` first, and inspect the new tables. Do not apply to production or development until tests pass.

BILL-01.1 contains the **data layer only**, not endpoints, checkout, provider webhooks, or CFDI issuance. Business rules such as one effective subscription per tenant must be enforced transactionally by the service layer in BILL-01.2 (the schema retains history). Price/entitlement changes should be versioned in service logic; do not modify an already subscribed price in place.
