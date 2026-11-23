
from pathlib import Path
import os
import time
from dotenv import load_dotenv
from flask import Flask, app, request, g, current_app
from flask_cors import CORS
from sqlalchemy.engine import make_url
from app.extensions import db, migrate, jwt_manager, limiter
from app.models.inventory_incident import InventoryIncident
from app.api.inventory_incidents import bp as inventory_incidents_bp
from app.models.inventory_adjustment import InventoryAdjustment
from app.models.inventory_incident_charge import InventoryIncidentCharge
from app.models.inventory_charge_audit import InventoryChargeAudit
from app.api.inventory_charges import bp as inventory_charges_bp
from app.swagger import init_swagger
from app.models.api_idempotency_key import ApiIdempotencyKey
from app.models.inventory_reservation_audit import InventoryReservationAudit
from app.models.logistics_order import LogisticsOrder
from app.models.logistics_order_item import LogisticsOrderItem
from app.api.logistics import bp as logistics_bp
from app.models.contract_payment import ContractPayment  # noqa: F401
from app.models.contract_payment_audit import ContractPaymentAudit  # noqa: F401
from app.models.company_receipt import CompanyReceiptSettings, IssuedPaymentReceipt  # noqa: F401
from app.api.quotes import bp as quotes_bp
from app.api.contracts import bp as contracts_bp
from app.api.signature_delivery import bp as signature_delivery_bp
from app.api.contract_payments import bp as contract_payments_bp
from app.models.billing import (
    BillingPlan,
    BillingPlanPrice,
    BillingPlanEntitlement,
    TenantSubscription,
    SubscriptionAudit,
    BillingPriceAudit,
)
from app.api.billing import bp as billing_bp
from app.api.billing_admin import bp as billing_admin_bp
from app.models.mercadopago import MPCheckout, MPWebhookEvent, MPPayment, MPReconciliationIssue  # noqa: F401
from app.api.mercadopago import bp as mercadopago_bp
_WEAK_SECRETS = {"", "dev-only-not-for-production", "replace-with-random-secret", "change-me"}


def _parse_id_list(raw):
    ids = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit() and int(part) > 0:
            ids.append(int(part))
    return frozenset(ids)


def _validate_production_config(app):
    """Fail fast on unsafe production settings instead of running insecurely."""
    problems = []
    for key in ("SECRET_KEY", "JWT_SECRET_KEY", "SIGNATURE_OTP_SECRET"):
        value = os.getenv(key) or app.config.get(key) or ""
        if value in _WEAK_SECRETS or len(value) < 32:
            problems.append(f"{key} debe tener al menos 32 caracteres aleatorios")
    if not app.config.get("MP_ACCESS_TOKEN"):
        problems.append("MP_ACCESS_TOKEN es obligatorio")
    if len(app.config.get("MP_WEBHOOK_SECRET") or "") < 16:
        problems.append("MP_WEBHOOK_SECRET es obligatorio")
    if not (app.config.get("MP_BACK_URL") or "").startswith("https://"):
        problems.append("MP_BACK_URL debe ser https://")
    origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
    if not origins or any(not o.startswith("https://") for o in origins):
        problems.append("CORS_ORIGINS debe listar solo orígenes https://")
    if not (os.getenv("FRONTEND_PUBLIC_URL") or "").startswith("https://"):
        problems.append("FRONTEND_PUBLIC_URL debe ser https://")
    if (app.config.get("RATELIMIT_STORAGE_URI") or "").startswith("memory://") and \
            os.getenv("RATELIMIT_ALLOW_MEMORY", "false").lower() not in ("true", "1"):
        problems.append("RATELIMIT_STORAGE_URI debe apuntar a un almacenamiento compartido (p. ej. redis://)")
    if problems:
        raise RuntimeError("Configuración de producción inválida: " + "; ".join(problems))


def create_app(config_override=None):

    # ==============================================
    # 1. VARIABLES DE ENTORNO
    # ==============================================

    base_dir = Path(__file__).resolve().parent.parent

   
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

    # Detrás de un proxy TLS (nginx/balanceador): número de proxies de confianza.
    # 0 = sin proxy (no se confía en X-Forwarded-*).
    trusted_proxies = int(os.getenv("TRUSTED_PROXY_COUNT", "0") or 0)
    if trusted_proxies > 0:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=trusted_proxies,
            # El proxy más cercano reenvía el esquema original (un solo valor).
            x_proto=1,
        )
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
    app.config["SIGNATURE_OTP_SECRET"] = os.getenv(
    "SIGNATURE_OTP_SECRET"
)
    # ==============================================
    # 4. CONFIGURACIÓN SQLALCHEMY
    # ==============================================

    if not db_url:
        raise RuntimeError(
        f"Falta configurar {env_config['database']} "
        f"para el ambiente {env}."
    )

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url

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
    app.config['MP_ACCESS_TOKEN'] = os.getenv('MP_ACCESS_TOKEN', '')
    app.config['MP_WEBHOOK_SECRET'] = os.getenv('MP_WEBHOOK_SECRET', '')
    app.config['MP_BACK_URL'] = os.getenv('MP_BACK_URL', '')
    # Minutos tras los cuales un checkout no autorizado deja de bloquear un nuevo intento.
    app.config['MP_CHECKOUT_PENDING_TTL_MINUTES'] = int(os.getenv('MP_CHECKOUT_PENDING_TTL_MINUTES', '30'))

    # Operadores globales de la plataforma (IDs de usuario separados por coma).
    app.config['BILLING_OPERATOR_USER_IDS'] = _parse_id_list(
        os.getenv('BILLING_OPERATOR_USER_IDS', '')
    )
    app.config['BILLING_ENFORCE_ENTITLEMENTS'] = (
        os.getenv('BILLING_ENFORCE_ENTITLEMENTS', 'false').lower() in ('true', '1', 'yes')
    )
    app.config['RATELIMIT_STORAGE_URI'] = os.getenv('RATELIMIT_STORAGE_URI', 'memory://')
    app.config['RATELIMIT_HEADERS_ENABLED'] = True
    # Las pruebas automatizadas registran muchos usuarios; el límite se prueba explícitamente.
    app.config['RATELIMIT_ENABLED'] = env != 'test'
    app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', str(20 * 1024 * 1024)))

    # ==============================================
    # 6. CONFIGURACIÓN ADICIONAL
    # ==============================================

    if config_override:
        app.config.update(config_override)

    # ==============================================
    # 7. VALIDAR CONFIGURACIÓN FINAL
    # ==============================================

    database_uri = app.config.get("SQLALCHEMY_DATABASE_URI")
    if not database_uri:
        raise RuntimeError(f"Falta la base de datos para el entorno {env}.")
    if not app.config.get("JWT_SECRET_KEY"):
        raise RuntimeError("Falta JWT_SECRET_KEY.")

    parsed_db_url = make_url(database_uri)
    backend = parsed_db_url.get_backend_name()

    if env == "test":
        is_mysql_test = (
            backend == "mysql"
            and parsed_db_url.database == "crm_events_test"
        )
        explicit_sqlite_override = (
            database_uri == "sqlite:///:memory:"
            and config_override is not None
            and config_override.get("TESTING") is True
            and config_override.get("SQLALCHEMY_DATABASE_URI")
            == "sqlite:///:memory:"
        )
        if explicit_sqlite_override:
            app.config["CHECK_DB_ON_STARTUP"] = False
        elif not is_mysql_test:
            raise RuntimeError(
                "Test solo permite MySQL crm_events_test o SQLite en memoria "
                "solicitado explícitamente por una prueba."
            )
    elif env == "development":
        if backend != "mysql" or parsed_db_url.database != "crm_events_dev":
            raise RuntimeError("Development requiere MySQL crm_events_dev.")
    elif env == "production":
        if backend != "mysql":
            raise RuntimeError("Production requiere MySQL.")
        _validate_production_config(app)

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

    app.config["UPLOAD_FOLDER"] = str(upload_path)

    # En test siempre se usan rutas aisladas, ignorando rutas de .env.
    # En otros entornos se respetan las rutas personalizadas existentes.
    if env == "test":
        documents_root = upload_path / "contract_documents"
        signatures_root = upload_path / "contract_signatures"
    else:
        documents_root = Path(
            app.config.get("CONTRACT_DOCUMENT_STORAGE_ROOT")
            or os.getenv("CONTRACT_DOCUMENT_STORAGE_ROOT")
            or str(upload_path / "contract_documents")
        ).expanduser()
        signatures_root = Path(
            app.config.get("CONTRACT_SIGNATURE_STORAGE_ROOT")
            or os.getenv("CONTRACT_SIGNATURE_STORAGE_ROOT")
            or str(upload_path / "contract_signatures")
        ).expanduser()

    if not documents_root.is_absolute():
        documents_root = base_dir / documents_root
    if not signatures_root.is_absolute():
        signatures_root = base_dir / signatures_root

    documents_root = documents_root.resolve()
    signatures_root = signatures_root.resolve()
    if documents_root == signatures_root:
        raise RuntimeError("Documentos y firmas no pueden compartir la misma carpeta")

    documents_root.mkdir(parents=True, exist_ok=True)
    signatures_root.mkdir(parents=True, exist_ok=True)
    app.config["CONTRACT_DOCUMENT_STORAGE_ROOT"] = str(documents_root)
    app.config["CONTRACT_SIGNATURE_STORAGE_ROOT"] = str(signatures_root)

    # ==============================================
    # 9. IMPORTAR MODELOS
    # ==============================================

    from app.models import Tenant  # noqa: F401
    from app.models.contract import Contract  # noqa: F401
    from app.models.contract_item import ContractItem  # noqa: F401
    from app.models.contract_status_history import ContractStatusHistory  # noqa: F401

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
    from app.api.billing_prices_admin import bp as billing_prices_admin_bp
    app.register_blueprint(billing_prices_admin_bp, url_prefix='/api/v1')
    # ==============================================
    # 10. INICIALIZAR EXTENSIONES
    # ==============================================

    db.init_app(app)

    migrate.init_app(
        app,
        db
    )

    jwt_manager.init_app(app)
    limiter.init_app(app)

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
    app.config["FRONTEND_PUBLIC_URL"] = os.getenv(
        "FRONTEND_PUBLIC_URL",
        "http://localhost:4200",
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
    from app.api.contract_documents import (
    bp as contract_documents_bp,
)


    from app.api.contract_signing import bp as contract_signing_bp
    from app.api.signature_read import bp as signature_read_bp
    from app.api.contract_signature_receipts import (
    bp as receipts_bp
)
    from app.api.contract_signature_admin import (
    bp as contract_signature_admin_bp
)
    from app.api.payment_receipts import bp as payment_receipts_bp
    from app.api.company_receipts import bp as company_receipts_bp

    app.register_blueprint(
        contract_signature_admin_bp,
        url_prefix="/api/v1"
    )

    app.register_blueprint(
        receipts_bp,
        url_prefix="/api/v1"
    )
    app.register_blueprint(
        signature_read_bp,
        url_prefix="/api/v1",
    )
    app.register_blueprint(
        contract_signing_bp,
        url_prefix="/api/v1",
    )
    app.register_blueprint(
        signature_delivery_bp,
        url_prefix="/api/v1"
    )
    app.register_blueprint(
            contract_documents_bp,
            url_prefix="/api/v1",
        )

    app.register_blueprint(
        inventory_capacity_alert_events_bp,
        url_prefix="/api/v1"
    )
    app.register_blueprint(
        inventory_replenishments_bp,
        url_prefix="/api/v1"
    )
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
    inventory_movements_bp,
    logistics_bp,
    quotes_bp,
    contracts_bp,
    contract_payments_bp,
    payment_receipts_bp,
    company_receipts_bp,
      billing_bp,
      billing_admin_bp,
      mercadopago_bp
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
    @app.before_request
    def start_request_timer():

        g.request_start_time = (
            time.perf_counter()
        )

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if env == "production":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    @app.errorhandler(413)
    def payload_too_large(_error):
        return {"error": "payload_too_large"}, 413

    @app.errorhandler(429)
    def rate_limited(_error):
        return {"error": "rate_limited"}, 429

    @app.errorhandler(500)
    def internal_error(_error):
        db.session.rollback()
        return {"error": "internal_server_error"}, 500

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
