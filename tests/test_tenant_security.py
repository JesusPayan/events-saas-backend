
from tests.test_identity import client, register, token


def test_invalid_jwt_rejected(client):
    response = client.get(
        "/api/v1/tenants/current",
        headers={
            "Authorization": "Bearer invalid.jwt.token",
            "X-Tenant-ID": "1"
        }
    )

    assert response.status_code == 401


def test_missing_tenant_header(client):
    response = register(
        client,
        "security@example.com",
        "empresa-security"
    )

    assert response.status_code == 201

    jwt_token = token(client, "security@example.com")

    response = client.get(
        "/api/v1/tenants/current",
        headers={
            "Authorization": f"Bearer {jwt_token}"
        }
    )

    assert response.status_code == 400


def test_cross_tenant_access_rejected(client):
    response_a = register(
        client,
        "security-a@example.com",
        "security-a"
    )

    response_b = register(
        client,
        "security-b@example.com",
        "security-b"
    )

    assert response_a.status_code == 201
    assert response_b.status_code == 201

    tenant_b = response_b.json["tenant_id"]

    jwt_a = token(client, "security-a@example.com")

    headers = {
        "Authorization": f"Bearer {jwt_a}",
        "X-Tenant-ID": str(tenant_b)
    }

    endpoints = [
        "/api/v1/tenants/current",
        "/api/v1/memberships",
        "/api/v1/clients",
        "/api/v1/events"
    ]

    for endpoint in endpoints:
        response = client.get(
            endpoint,
            headers=headers
        )

        assert response.status_code == 403, (
            f"{endpoint} permitió acceso o devolvió "
            f"un estado inesperado: {response.status_code}"
        )
