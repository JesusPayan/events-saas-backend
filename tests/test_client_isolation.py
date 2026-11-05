
import pytest

from app.extensions import db
from app.models.crm import Client
from tests.test_identity import client, register, token


@pytest.fixture
def tenants(client):
    response_a = register(
        client,
        "clients-a@example.com",
        "clients-a"
    )

    response_b = register(
        client,
        "clients-b@example.com",
        "clients-b"
    )

    assert response_a.status_code == 201, response_a.get_json()
    assert response_b.status_code == 201, response_b.get_json()

    tenant_a = response_a.json["tenant_id"]
    tenant_b = response_b.json["tenant_id"]

    def headers(email, tenant_id):
        return {
            "Authorization": f"Bearer {token(client, email)}",
            "X-Tenant-ID": str(tenant_id)
        }

    return {
        "client": client,
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "headers_a": headers("clients-a@example.com", tenant_a),
        "headers_b": headers("clients-b@example.com", tenant_b)
    }


def create_customer(client, headers, first_name):
    response = client.post(
        "/api/v1/clients",
        headers=headers,
        json={
            "client_type": "individual",
            "first_name": first_name,
            "last_name": "Prueba",
            "email": f"{first_name.lower()}@example.com"
        }
    )

    assert response.status_code == 201, response.get_json()
    return response.json


def test_clients_are_isolated_in_lists(tenants):
    client = tenants["client"]

    customer_a = create_customer(
        client, tenants["headers_a"], "Ana"
    )
    customer_b = create_customer(
        client, tenants["headers_b"], "Carlos"
    )

    response_a = client.get(
        "/api/v1/clients",
        headers=tenants["headers_a"]
    )
    response_b = client.get(
        "/api/v1/clients",
        headers=tenants["headers_b"]
    )

    assert response_a.status_code == 200
    assert response_b.status_code == 200

    ids_a = {item["id"] for item in response_a.json["items"]}
    ids_b = {item["id"] for item in response_b.json["items"]}

    assert customer_a["id"] in ids_a
    assert customer_b["id"] not in ids_a

    assert customer_b["id"] in ids_b
    assert customer_a["id"] not in ids_b


def test_cannot_read_other_tenant_client(tenants):
    client = tenants["client"]

    customer_b = create_customer(
        client, tenants["headers_b"], "Carlos"
    )

    response = client.get(
        f"/api/v1/clients/{customer_b['id']}",
        headers=tenants["headers_a"]
    )

    assert response.status_code == 404


def test_cannot_update_other_tenant_client(tenants):
    client = tenants["client"]

    customer_b = create_customer(
        client, tenants["headers_b"], "Carlos"
    )

    response = client.patch(
        f"/api/v1/clients/{customer_b['id']}",
        headers=tenants["headers_a"],
        json={"first_name": "Modificado"}
    )

    assert response.status_code == 404

    original = client.get(
        f"/api/v1/clients/{customer_b['id']}",
        headers=tenants["headers_b"]
    )

    assert original.status_code == 200
    assert original.json["first_name"] == "Carlos"


def test_cannot_deactivate_other_tenant_client(tenants):
    client = tenants["client"]

    customer_b = create_customer(
        client, tenants["headers_b"], "Carlos"
    )

    response = client.patch(
        f"/api/v1/clients/{customer_b['id']}/deactivate",
        headers=tenants["headers_a"]
    )

    assert response.status_code == 404

    original = client.get(
        f"/api/v1/clients/{customer_b['id']}",
        headers=tenants["headers_b"]
    )

    assert original.status_code == 200
    assert original.json["status"] == "active"


def test_clients_store_correct_tenant_id(tenants):
    client = tenants["client"]

    customer_a = create_customer(
        client, tenants["headers_a"], "Ana"
    )
    customer_b = create_customer(
        client, tenants["headers_b"], "Carlos"
    )

    with client.application.app_context():
        stored_a = db.session.get(Client, customer_a["id"])
        stored_b = db.session.get(Client, customer_b["id"])

        assert stored_a.tenant_id == tenants["tenant_a"]
        assert stored_b.tenant_id == tenants["tenant_b"]
