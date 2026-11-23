"""Siembra idempotente del catálogo de planes (no reescribe precios existentes).

Uso:
  FLASK_ENV=development python -m scripts.seed_billing_catalog
  FLASK_ENV=production  python -m scripts.seed_billing_catalog --allow-production --confirm-database <nombre_bd>

En producción exige ambas banderas para evitar ejecuciones accidentales.
"""
import argparse
import os
from sqlalchemy.engine import make_url
from app import create_app
from app.extensions import db
from app.services.billing.catalog_seed import seed_billing_catalog, seed_free_tier


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--confirm-database", default="")
    args = parser.parse_args(argv)

    environment = os.environ.get("FLASK_ENV", "").lower()
    if environment not in {"test", "development", "production"}:
        raise SystemExit("Define FLASK_ENV=test, development o production explícitamente")
    if environment == "production" and not args.allow_production:
        raise SystemExit("Producción requiere --allow-production --confirm-database <nombre_bd>")

    app = create_app({"CHECK_DB_ON_STARTUP": False})
    with app.app_context():
        url = make_url(app.config["SQLALCHEMY_DATABASE_URI"])
        if url.get_backend_name() != "mysql":
            raise SystemExit("Bloqueado: se requiere MySQL")
        if environment == "production":
            if not args.confirm_database or args.confirm_database != url.database:
                raise SystemExit(f"Bloqueado: --confirm-database no coincide con la base configurada ({url.database!r})")
        else:
            expected = "crm_events_test" if environment == "test" else "crm_events_dev"
            if url.database != expected:
                raise SystemExit(f"Bloqueado: FLASK_ENV={environment} requiere MySQL {expected}; recibido {url.database!r}")
        try:
            print("Seed completed:", seed_billing_catalog())
            print("Free tier:", seed_free_tier())
        finally:
            db.session.remove()


if __name__ == "__main__":
    main()
