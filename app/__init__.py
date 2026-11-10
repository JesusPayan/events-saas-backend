
from pathlib import Path
import os
import time
from dotenv import load_dotenv
from flask import Flask, app, request, g, current_app, send_file
from flask_cors import CORS
from sqlalchemy.engine import make_url
from app.extensions import db, migrate, jwt_manager
from app.models.inventory_incident import InventoryIncident
from app.api.inventory_incidents import bp as inventory_incidents_bp
from app.models.inventory_adjustment import InventoryAdjustment
from app.models.inventory_incident_charge import InventoryIncidentCharge
from app.models.inventory_charge_audit import InventoryChargeAudit
from app.api.inventory_charges import bp as inventory_charges_bp
from flask_swagger_ui import get_swaggerui_blueprint
from app.swagger import init_swagger
from app.models.api_idempotency_key import ApiIdempotencyKey
from app.models.inventory_reservation_audit import InventoryReservationAudit
from app.models.logistics_order import LogisticsOrder
from app.models.logistics_order_item import LogisticsOrderItem

def create_app(config_override=None):

    # ==============================================
    # 1. VARIABLES DE ENTORNO
    # ==============================================

    base_dir = Path(__file__).resolve().parent.parent
    # openapi_path = Path(app.root_path).parent / "openapi.json"

   
    swagger_ui = get_swaggerui_blueprint(
        "/api/docs",
        "/api/openapi.json",
        config={"app_name": "Eventos SaaS API"}
    )

    load_dotenv(base_dir / ".env")

    env = os.getenv(
        "FLASK_ENV",
        "development"
    ).lower()

    # ==============================================
    # 2. CREAR APLICACIÓN
    # ==============================================

    app = Flask(__name__)

    app.config.from_object("app.config.Config")
    app.config["CHECK_DB_ON_STARTUP"] = (
        os.getenv("CHECK_DB_ON_STARTUP", "true").lower()
        in ("true", "1", "yes")
    )
    # ==============================================
    # 3. CONFIGURACIÓN POR ENTORNO
    # ==============================================

    environments = {
        "development": {
            "database": "DB_URL_DEV",
            "uploads": "UPLOAD_FOLDER_LOCAL"
        },
        "test": {
            "database": "DB_URL_TEST",
            "uploads": "UPLOAD_FOLDER_TEST"
        },
        "production": {
            "database": "DB_URL_PROD",
            "uploads": "UPLOAD_FOLDER_PROD"
        }
    }

    if env not in environments:
        raise RuntimeError(
            f"Entorno no reconocido: {env}"
        )

    env_config = environments[env]

    db_url = os.getenv(
        env_config["database"]
    )

    upload_folder = os.getenv(
        env_config["uploads"]
    )

    # ==============================================
    # 4. CONFIGURACIÓN SQLALCHEMY
    # ==============================================

    if db_url:
        app.config[
            "SQLALCHEMY_DATABASE_URI"
        ] = db_url

    app.config[
        "SQLALCHEMY_TRACK_MODIFICATIONS"
    ] = False

    # ==============================================
    # 5. CONFIGURACIÓN JWT
    # ==============================================

    jwt_secret = os.getenv(
        "JWT_SECRET_KEY"
    )

    if jwt_secret:
        app.config[
            "JWT_SECRET_KEY"
        ] = jwt_secret

    # ==============================================
    # 6. CONFIGURACIÓN ADICIONAL
    # ==============================================

    if config_override:
        app.config.update(config_override)

    # ==============================================
    # 7. VALIDAR CONFIGURACIÓN FINAL
    # ==============================================

    database_uri = app.config.get(
        "SQLALCHEMY_DATABASE_URI"
    )

    if not database_uri:
        raise RuntimeError(
            "Falta la configuración de base de datos "
            f"para el entorno {env}."
        )

    if not app.config.get("JWT_SECRET_KEY"):
        raise RuntimeError(
            "Falta JWT_SECRET_KEY."
        )

    safe_uri = make_url(
        database_uri
    ).render_as_string(
        hide_password=True
    )

    app.logger.info(
        "Entorno: %s",
        env
    )

    app.logger.info(
        "Base de datos: %s",
        safe_uri
    )

    # ==============================================
    # 8. CONFIGURAR CARPETA DE ARCHIVOS
    # ==============================================

    upload_path = Path(
        upload_folder
        or str(base_dir / "uploads" / env)
    ).expanduser()

    if not upload_path.is_absolute():
        upload_path = base_dir / upload_path

    upload_path.mkdir(
        parents=True,
        exist_ok=True
    )

    app.config[
        "UPLOAD_FOLDER"
    ] = str(upload_path)

    # ==============================================
    # 9. IMPORTAR MODELOS
    # ==============================================

    from app.models import Tenant  # noqa: F401

    from app.models.crm import Client  # noqa: F401
    from app.models.event import Event  # noqa: F401

    from app.models.inventory_category import (
        InventoryCategory
    )

    from app.models.inventory_item import (
        InventoryItem
    )

    from app.models.inventory_reservation import (
        InventoryReservation
    )

    from app.models.inventory_movement import (
        InventoryMovement
    )

    # ==============================================
    # 10. INICIALIZAR EXTENSIONES
    # ==============================================

    db.init_app(app)

    migrate.init_app(
        app,
        db
    )

    jwt_manager.init_app(app)

    # ==============================================
    # 11. VERIFICAR CONEXIÓN
    # ==============================================

    if app.config.get(
        "CHECK_DB_ON_STARTUP",
        True
    ):

        with app.app_context():

            app.logger.info(
                "Estado del pool: %s",
                db.engine.pool.status()
            )

            try:
                with db.engine.connect():
                    app.logger.info(
                        "Conexión a la base de datos exitosa."
                    )

            except Exception:
                app.logger.exception(
                    "No fue posible conectar con la base de datos."
                )
                raise

    # ==============================================
    # 12. CONFIGURAR CORS
    # ==============================================

    allowed_origins = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:4200,"
        "http://127.0.0.1:4200"
    ).split(",")
    # @app.get("/api/openapi.json")
    # def openapi_spec():
    #         return send_file(openapi_path, mimetype="application/json")
    init_swagger(app)
    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": [
                    origin.strip()
                    for origin in allowed_origins
                    if origin.strip()
                ]
            }
        }
    )

    # ==============================================
    # 13. IMPORTAR BLUEPRINTS
    # ==============================================

    from app.api.health import bp as health_bp
    from app.api.auth import bp as auth_bp
    from app.api.clients import bp as clients_bp
    from app.api.events import bp as events_bp
    from app.api.inventory_operations import (
    bp as inventory_operations_bp
)

    from app.api.inventory import (
        bp as inventory_bp
    )

    from app.api.inventory_reservations import (
        bp as inventory_reservations_bp
    )

    from app.api.inventory_movements import (
        bp as inventory_movements_bp
    )

    from app.api.inventory_replenishments import (
    bp as inventory_replenishments_bp
)

    from app.api.inventory_capacity_alert_events import (
    bp as inventory_capacity_alert_events_bp
)

    app.register_blueprint(
    inventory_capacity_alert_events_bp,
    url_prefix="/api/v1"
)
    app.register_blueprint(
    inventory_replenishments_bp,
    url_prefix="/api/v1"
)
    # app.register_blueprint(swagger_ui, url_prefix="/api/docs")
    app.register_blueprint(
    inventory_incidents_bp,
    url_prefix="/api/v1"
)
    app.register_blueprint(
    inventory_charges_bp,
    url_prefix="/api/v1"
)
    # ==============================================
    # 14. REGISTRAR BLUEPRINTS
    # ==============================================

    blueprints = [
        health_bp,
        auth_bp,
        clients_bp,
        events_bp,
        inventory_bp,
        inventory_reservations_bp,
        inventory_movements_bp
    ]


    for blueprint in blueprints:
        app.register_blueprint(
            blueprint,
            url_prefix="/api/v1"
        )
    app.register_blueprint(
    inventory_operations_bp,
    url_prefix="/api/v1"
)
    # ==============================================
    # 15. MEDIR TIEMPOS HTTP
    # ==============================================
    from app.api.quotes import bp as quotes_bp

    app.register_blueprint(
        quotes_bp,
        url_prefix="/api/v1"
    )
    @app.before_request
    def start_request_timer():

        g.request_start_time = (
            time.perf_counter()
        )

    @app.after_request
    def log_request_duration(response):

        start = getattr(
            g,
            "request_start_time",
            None
        )

        if start is None:
            return response

        elapsed_ms = (
            time.perf_counter() - start
        ) * 1000

        current_app.logger.info(
            "HTTP %s %s -> %s | %.2f ms",
            request.method,
            request.path,
            response.status_code,
            elapsed_ms
        )

        return response

    # ==============================================
    # 16. FINALIZAR
    # ==============================================

    app.logger.info(
        "Aplicación Flask inicializada."
    )

    app.logger.info(
        "Carpeta de archivos: %s",
        upload_path
    )

    return app
