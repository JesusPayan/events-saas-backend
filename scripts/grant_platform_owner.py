"""Designa al primer dueño de la plataforma (ROLES-01).

Solo funciona si todavía no hay dueño; después, la propiedad se transfiere desde
el panel de plataforma (Roles de plataforma → Transferir propiedad).

Uso:
  FLASK_ENV=development python -m scripts.grant_platform_owner --email tu@correo.com
  FLASK_ENV=production  python -m scripts.grant_platform_owner --email tu@correo.com --allow-production --confirm-database <nombre_bd>

La cuenta debe existir (regístrala antes en la aplicación).
"""
import argparse
import os

from sqlalchemy.engine import make_url

from app import create_app
from app.services.platform_service import PlatformError, bootstrap_owner


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
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
        if environment == "production" and args.confirm_database != url.database:
            raise SystemExit(f"Bloqueado: --confirm-database no coincide con la base configurada ({url.database!r})")
        try:
            row = bootstrap_owner(args.email)
        except PlatformError as exc:
            raise SystemExit(f"No se asignó: {exc.code}")
        print(f"Dueño de plataforma asignado: user_id={row.user_id}")


if __name__ == "__main__":
    main()
