
"""COM-02.1.11.3: autenticación y aislamiento multiempresa."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask

from app.api.contract_signature_admin import bp
from app.security import issue_token


URL = (
    "/api/v1/contracts/1/"
    "signature-management/documents/1/pdf"
)


@pytest.fixture
def environment():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="solo-para-pruebas-automatizadas",
    )

    # Conservamos los decoradores originales.
    app.register_blueprint(bp, url_prefix="/api/v1")

    with app.app_context():
        token = issue_token(100)

        with app.test_client() as client:
            yield client, token


def headers(token, tenant_id=1):
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-ID": str(tenant_id),
    }


def mock_database(*, membership=True, permission=True, document=None):
    """
    Simula únicamente las consultas necesarias para
    comprobar autenticación, autorización y aislamiento.
    """

    user = SimpleNamespace(
        id=100,
        is_active=True,
    )

    member = SimpleNamespace(
        user_id=100,
        tenant_id=1,
        role_id=10,
        status="active",
    )

    def scalar(statement):
        sql = str(statement).lower()

        if "memberships" in sql:
            return member if membership else None

        if "permissions" in sql:
            return 1 if permission else None

        if "contract_documents" in sql:
            return document

        raise AssertionError(
            f"Consulta inesperada durante la prueba: {sql}"
        )

    return (
        patch(
            "app.security.db.session.get",
            return_value=user,
        ),
        patch(
            "app.security.db.session.scalar",
            side_effect=scalar,
        ),
    )


def test_sin_token_retorna_401(environment):
    client, _ = environment

    response = client.get(
        URL,
        headers={"X-Tenant-ID": "1"},
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "authentication_required"


def test_token_invalido_retorna_401(environment):
    client, _ = environment

    response = client.get(
        URL,
        headers=headers("token-invalido"),
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "invalid_token"


def test_usuario_sin_membership_retorna_403(environment):
    client, token = environment
    mock_user, mock_scalar = mock_database(membership=False)

    with mock_user, mock_scalar:
        response = client.get(URL, headers=headers(token))

    assert response.status_code == 403
    assert response.get_json()["error"] == "forbidden"


def test_usuario_sin_permiso_retorna_403(environment):
    client, token = environment
    mock_user, mock_scalar = mock_database(permission=False)

    with mock_user, mock_scalar:
        response = client.get(URL, headers=headers(token))

    assert response.status_code == 403
    assert response.get_json()["error"] == "forbidden"


def test_documento_no_pertenece_al_tenant_retorna_404(environment):
    client, token = environment
    mock_user, mock_scalar = mock_database(
        membership=True,
        permission=True,
        document=None,
    )

    with mock_user, mock_scalar:
        response = client.get(URL, headers=headers(token))

    assert response.status_code == 404
    assert response.get_json()["error"] == "document_not_found"
