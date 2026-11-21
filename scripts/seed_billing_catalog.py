"""Run from project root: python -m scripts.seed_billing_catalog"""
import os
from sqlalchemy.engine import make_url
from app import create_app
from app.extensions import db
from app.services.billing.catalog_seed import seed_billing_catalog


def main():
    environment = os.environ.get("FLASK_ENV", "").lower()
    if environment not in {"test", "development"}:
        raise SystemExit("Set FLASK_ENV=test or development explicitly; production seeding is disabled")
    app = create_app({"CHECK_DB_ON_STARTUP": False})
    with app.app_context():
        url = make_url(app.config["SQLALCHEMY_DATABASE_URI"])
        expected = "crm_events_test" if environment == "test" else "crm_events_dev"
        if url.get_backend_name() != "mysql" or url.database != expected:
            raise SystemExit(f"Blocked: FLASK_ENV={environment} requires MySQL {expected}; got {url.database!r}")
        try:
            print("Seed completed:", seed_billing_catalog())
        finally:
            db.session.remove()


if __name__ == "__main__":
    main()
