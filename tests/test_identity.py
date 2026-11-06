
import sqlite3

import pytest

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.extensions import db
from app.models.identity import Role, Membership


# Habilitar claves foráneas para SQLite
@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_keys(
    dbapi_connection,
    connection_record
):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest.fixture
def client():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SECRET_KEY": "test-key",
        "JWT_SECRET_KEY": "test-jwt-key",
        "CHECK_DB_ON_STARTUP": False
    })

    with app.app_context():
        db.create_all()

        # Verificar que SQLite valide claves foráneas
        foreign_keys_enabled = db.session.execute(
            text("PRAGMA foreign_keys")
        ).scalar()

        assert foreign_keys_enabled == 1, (
            "Las claves foráneas de SQLite están desactivadas"
        )

        yield app.test_client()

        db.session.remove()
        db.drop_all()


def register(client, email, slug):
    return client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "a-very-long-password",
            "company_name": "Empresa " + slug,
            "slug": slug
        }
    )


def token(client, email):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": "a-very-long-password"
        }
    )

    assert response.status_code == 200, response.get_json()

    return response.json["access_token"]


def test_register_login_and_isolation(client):
    # Registrar dos empresas independientes
    a = register(client, "a@example.com", "empresa-a")
    b = register(client, "b@example.com", "empresa-b")

    assert a.status_code == 201, a.get_json()
    assert b.status_code == 201, b.get_json()

    tenant_a = a.json["tenant_id"]
    tenant_b = b.json["tenant_id"]

    assert tenant_a != tenant_b

    # Autenticación del usuario de empresa A
    bearer = "Bearer " + token(client, "a@example.com")

    # Puede acceder a su empresa
    response = client.get(
        "/api/v1/tenants/current",
        headers={
            "Authorization": bearer,
            "X-Tenant-ID": str(tenant_a)
        }
    )
    assert response.status_code == 200

    # No puede acceder a empresa B
    response = client.get(
        "/api/v1/tenants/current",
        headers={
            "Authorization": bearer,
            "X-Tenant-ID": str(tenant_b)
        }
    )
    assert response.status_code == 403

    # No puede consultar membresías de empresa B
    response = client.get(
        "/api/v1/memberships",
        headers={
            "Authorization": bearer,
            "X-Tenant-ID": str(tenant_b)
        }
    )
    assert response.status_code == 403

    # No puede acceder sin autenticación
    response = client.get(
        "/api/v1/tenants/current",
        headers={
            "X-Tenant-ID": str(tenant_a)
        }
    )
    assert response.status_code == 401


def test_duplicate_and_wrong_password(client):
    # Registro correcto
    response = register(
        client,
        "a@example.com",
        "empresa-a"
    )
    assert response.status_code == 201

    # Correo duplicado
    response = register(
        client,
        "a@example.com",
        "empresa-b"
    )
    assert response.status_code == 409

    # Contraseña incorrecta
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "a@example.com",
            "password": "incorrect"
        }
    )
    assert response.status_code == 401


def test_cross_tenant_role_rejected(client):
    # Crear dos empresas
    response_a = register(
        client,
        "a@example.com",
        "empresa-a"
    )
    response_b = register(
        client,
        "b@example.com",
        "empresa-b"
    )

    assert response_a.status_code == 201
    assert response_b.status_code == 201

    tenant_a = response_a.json["tenant_id"]
    tenant_b = response_b.json["tenant_id"]

    with client.application.app_context():
        # Obtener rol de empresa B
        role_b = db.session.query(Role).filter_by(
            tenant_id=tenant_b
        ).one()

        # Obtener membresía de empresa A
        member_a = db.session.query(Membership).filter_by(
            tenant_id=tenant_a
        ).one()

        original_role_id = member_a.role_id

        # Intentar asignar rol de otra empresa
        member_a.role_id = role_b.id

        # La base de datos debe rechazarlo
        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()

        # Confirmar que el rol original se conserva
        db.session.refresh(member_a)

        assert member_a.role_id == original_role_id
