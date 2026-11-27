
import os
from urllib.parse import urlsplit

import pytest
import requests

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app import create_app
from app.extensions import db
from app.models import Tenant
from app.models.identity import (
    User,
    Membership,
    Role,
    Permission,
    RolePermission,
)
from app.security import issue_token


# ==========================================================
# CONFIGURACIÓN DE FLASK PARA PRUEBAS
# ==========================================================

@pytest.fixture(scope="session")
def flask_app():

    os.environ["FLASK_ENV"] = "test"

    app = create_app({
        "TESTING": True,
        "CHECK_DB_ON_STARTUP": False,
    })

    url = make_url(
        app.config["SQLALCHEMY_DATABASE_URI"]
    )

    # Evitar pruebas sobre desarrollo o producción
    if (
        url.get_backend_name() != "mysql"
        or url.database != "crm_events_test"
    ):
        pytest.fail(
            "La prueba requiere MySQL crm_events_test"
        )

    return app


# ==========================================================
# TENANT, USUARIO, ROL Y PERMISOS DE PRUEBAS
# ==========================================================

@pytest.fixture(scope="session")
def test_context(flask_app):

    with flask_app.app_context():

        try:

            # --------------------------------------------------
            # 1. CREAR O RECUPERAR TENANT
            # --------------------------------------------------

            tenant = db.session.scalar(
                select(Tenant).where(
                    Tenant.slug == "empresa-concurrency-test"
                )
            )

            if tenant is None:

                tenant = Tenant(
                    name="Empresa Concurrency Test",
                    slug="empresa-concurrency-test",
                    status="active",
                    timezone="America/Mazatlan",
                )

                db.session.add(tenant)
                db.session.flush()

            # --------------------------------------------------
            # 2. CREAR O RECUPERAR USUARIO
            # --------------------------------------------------

            user = db.session.scalar(
                select(User).where(
                    User.email == "ci-concurrency@example.test"
                )
            )

            if user is None:

                user = User(
                    email="ci-concurrency@example.test",
                    password_hash="CI_ONLY_NO_PASSWORD_LOGIN",
                    is_active=True,
                )

                db.session.add(user)
                db.session.flush()

            # --------------------------------------------------
            # 3. CREAR O RECUPERAR ROL
            # --------------------------------------------------

            role = db.session.scalar(
                select(Role).where(
                    Role.tenant_id == tenant.id,
                    Role.name == "ci_inventory_tester",
                )
            )

            if role is None:

                role = Role(
                    tenant_id=tenant.id,
                    name="ci_inventory_tester",
                )

                db.session.add(role)
                db.session.flush()

            # --------------------------------------------------
            # 4. ASIGNAR PERMISOS DE INVENTARIO
            # --------------------------------------------------

            required_permissions = (
                "inventory.create",
                "inventory.update",
                "inventory.read",
                "inventory.adjust",
            )

            for permission_code in required_permissions:

                permission = db.session.scalar(
                    select(Permission).where(
                        Permission.code == permission_code
                    )
                )

                if permission is None:

                    permission = Permission(
                        code=permission_code
                    )

                    db.session.add(permission)
                    db.session.flush()

                role_permission = db.session.get(
                    RolePermission,
                    (role.id, permission.id),
                )

                if role_permission is None:

                    db.session.add(
                        RolePermission(
                            role_id=role.id,
                            permission_id=permission.id,
                        )
                    )

            # --------------------------------------------------
            # 5. CREAR O ACTUALIZAR MEMBRESÍA
            # --------------------------------------------------

            membership = db.session.scalar(
                select(Membership).where(
                    Membership.tenant_id == tenant.id,
                    Membership.user_id == user.id,
                )
            )

            if membership is None:

                membership = Membership(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    role_id=role.id,
                    status="active",
                )

                db.session.add(membership)

            else:

                membership.role_id = role.id
                membership.status = "active"

            # --------------------------------------------------
            # 6. ASEGURAR ESTADOS ACTIVOS
            # --------------------------------------------------

            tenant.status = "active"
            user.is_active = True

            # --------------------------------------------------
            # 7. CONFIRMAR TRANSACCIÓN
            # --------------------------------------------------

            db.session.commit()

            # --------------------------------------------------
            # 8. GENERAR TOKEN JWT
            # --------------------------------------------------

            context = {
                "tenant_id": tenant.id,
                "user_id": user.id,
                "token": issue_token(user.id),
            }

            return context

        except Exception:

            db.session.rollback()
            raise

        finally:

            db.session.remove()


# ==========================================================
# ESCENARIO DE CONCURRENCIA DE CONCILIACIÓN
# ==========================================================

@pytest.fixture
def reconciliation_scenario(flask_app, test_context):

    from tests.integration.test_reconciliation_concurrency import (
    create_reconciliation_scenario,
    )

    # --------------------------------------------------
    # 1. CONFIGURAR URL DEL SERVIDOR DE PRUEBAS
    # --------------------------------------------------

    base_url = os.environ.get(
        "API_BASE_URL",
        "http://127.0.0.1:5001/api/v1",
    ).rstrip("/")

    parsed = urlsplit(base_url)

    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("127.0.0.1", "localhost")
        or parsed.port not in (5001, 5002)
        or parsed.path != "/api/v1"
    ):
        pytest.fail(
            "API_BASE_URL debe ser "
            "http://127.0.0.1:5001/api/v1"
        )

    # --------------------------------------------------
    # 2. VALIDAR DISPONIBILIDAD DEL SERVIDOR
    # --------------------------------------------------

    try:

        response = requests.get(
            f"{base_url}/health",
            timeout=5,
        )

        response.raise_for_status()

    except requests.RequestException as exc:

        pytest.fail(
            f"Servidor de pruebas no disponible: {exc}"
        )

    # --------------------------------------------------
    # 3. CREAR ESCENARIO DE CONCILIACIÓN
    # --------------------------------------------------

    with flask_app.app_context():

        try:

            scenario = create_reconciliation_scenario(
                test_context
            )

        finally:

            db.session.remove()

    # --------------------------------------------------
    # 4. CONFIGURAR ENDPOINT
    # --------------------------------------------------

    scenario["url"] = (
        f"{base_url}/inventory/incidents/"
        f"{scenario['incident_id']}/reconcile"
    )

    # --------------------------------------------------
    # 5. CONFIGURAR HEADERS DE AUTENTICACIÓN
    # --------------------------------------------------

    scenario["headers"] = {
        "Authorization": (
            f"Bearer {test_context['token']}"
        ),
        "X-Tenant-ID": str(scenario["tenant_id"]),
        "Content-Type": "application/json",
    }

    return scenario


# ==========================================================
# MOD-01: organizaciones de prueba con todos los módulos
# ==========================================================

def pytest_configure(config):
    config.addinivalue_line("markers", "mod01: pruebas de MOD-01 con la configuración real de módulos")


@pytest.fixture(autouse=True)
def _pre_mod01_full_modules(request, monkeypatch):
    """Las pruebas anteriores a MOD-01 asumen que una empresa recién registrada usa todos
    los módulos (como en v1.2.0). Para ellas, la configuración inicial incluye todos los
    módulos disponibles; la verificación de módulos en el servidor sigue activa.

    Las pruebas marcadas con ``@pytest.mark.mod01`` usan la configuración real
    (solo módulos comunes hasta completar el onboarding).
    """
    if request.node.get_closest_marker("mod01") is None:
        from app.modules_registry import OPTIONAL_MODULES
        monkeypatch.setattr("app.services.capability_service.DEFAULT_NEW_TENANT_MODULES", OPTIONAL_MODULES)
