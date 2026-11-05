
import pytest

from app.extensions import db
from app.models.event import Event
from tests.test_identity import client
from tests.test_client_isolation import tenants, create_customer


def create_event(client, headers, client_id, name):
    response = client.post(
        "/api/v1/events",
        headers=headers,
        json={
            "client_id": client_id,
            "name": name,
            "event_type": "wedding",
            "starts_at": "2027-03-10T16:00:00Z",
            "ends_at": "2027-03-10T23:00:00Z",
            "estimated_guests": 100
        }
    )

    assert response.status_code == 201, response.get_json()
    return response.json


@pytest.fixture
def event_data(tenants):
    client = tenants["client"]
    headers_a = tenants["headers_a"]
    headers_b = tenants["headers_b"]

    # # Diagnóstico temporal de permisos
    # permissions_response = client.get(
    #     "/api/v1/auth/permissions",
    #     headers=headers_a
    # )

    # print(
    #     "\nPERMISOS EMPRESA A:",
    #     permissions_response.status_code,
    #     permissions_response.get_json()
    # )

    customer_a = create_customer(
        client, headers_a, "Ana"
    )

    customer_b = create_customer(
        client, headers_b, "Carlos"
    )

    event_a = create_event(
        client, headers_a, customer_a["id"], "Boda Ana"
    )

    event_b = create_event(
        client, headers_b, customer_b["id"], "Fiesta Carlos"
    )

    return {
        **tenants,
        "customer_a": customer_a,
        "customer_b": customer_b,
        "event_a": event_a,
        "event_b": event_b
    }

def test_events_are_isolated_in_lists(event_data):
    client = event_data["client"]

    response_a = client.get(
        "/api/v1/events",
        headers=event_data["headers_a"]
    )
    response_b = client.get(
        "/api/v1/events",
        headers=event_data["headers_b"]
    )

    assert response_a.status_code == 200
    assert response_b.status_code == 200

    ids_a = {e["id"] for e in response_a.json["items"]}
    ids_b = {e["id"] for e in response_b.json["items"]}

    assert event_data["event_a"]["id"] in ids_a
    assert event_data["event_b"]["id"] not in ids_a
    assert event_data["event_b"]["id"] in ids_b
    assert event_data["event_a"]["id"] not in ids_b


def test_cannot_read_other_tenant_event(event_data):
    response = event_data["client"].get(
        f"/api/v1/events/{event_data['event_b']['id']}",
        headers=event_data["headers_a"]
    )

    assert response.status_code == 404


def test_cannot_update_other_tenant_event(event_data):
    client = event_data["client"]
    event_b_id = event_data["event_b"]["id"]

    response = client.patch(
        f"/api/v1/events/{event_b_id}",
        headers=event_data["headers_a"],
        json={"name": "Evento modificado"}
    )

    assert response.status_code == 404

    original = client.get(
        f"/api/v1/events/{event_b_id}",
        headers=event_data["headers_b"]
    )

    assert original.status_code == 200
    assert original.json["name"] == "Fiesta Carlos"


def test_cannot_change_other_tenant_event_status(event_data):
    client = event_data["client"]
    event_b_id = event_data["event_b"]["id"]

    response = client.patch(
        f"/api/v1/events/{event_b_id}/status",
        headers=event_data["headers_a"],
        json={"status": "quoted"}
    )

    assert response.status_code == 404

    original = client.get(
        f"/api/v1/events/{event_b_id}",
        headers=event_data["headers_b"]
    )

    assert original.status_code == 200
    assert original.json["status"] == "draft"


def test_cannot_create_event_with_other_tenant_client(event_data):
    response = event_data["client"].post(
        "/api/v1/events",
        headers=event_data["headers_a"],
        json={
            "client_id": event_data["customer_b"]["id"],
            "name": "Evento indebido",
            "event_type": "wedding",
            "starts_at": "2027-04-10T16:00:00Z",
            "ends_at": "2027-04-10T23:00:00Z",
        }
    )

    assert response.status_code == 404
    assert response.json["error"] == "client_not_found"


def test_cannot_assign_other_tenant_client(event_data):
    client = event_data["client"]
    event_a_id = event_data["event_a"]["id"]

    response = client.patch(
        f"/api/v1/events/{event_a_id}",
        headers=event_data["headers_a"],
        json={"client_id": event_data["customer_b"]["id"]}
    )

    assert response.status_code == 404

    original = client.get(
        f"/api/v1/events/{event_a_id}",
        headers=event_data["headers_a"]
    )

    assert original.status_code == 200
    assert original.json["client_id"] == event_data["customer_a"]["id"]


def test_events_store_correct_tenant_id(event_data):
    client = event_data["client"]

    with client.application.app_context():
        stored_a = db.session.get(
            Event, event_data["event_a"]["id"]
        )
        stored_b = db.session.get(
            Event, event_data["event_b"]["id"]
        )

        assert stored_a.tenant_id == event_data["tenant_a"]
        assert stored_b.tenant_id == event_data["tenant_b"]


def test_calendar_does_not_expose_other_tenant_events(event_data):
    client = event_data["client"]

    response = client.get(
        "/api/v1/events/calendar",
        headers=event_data["headers_a"],
        query_string={
            "from": "2027-03-01T00:00:00Z",
            "to": "2027-04-01T00:00:00Z"
        }
    )

    assert response.status_code == 200, response.get_json()

    events = response.get_json()

    event_a_id = event_data["event_a"]["id"]
    event_b_id = event_data["event_b"]["id"]

    event_ids = {event["id"] for event in events}

    assert event_a_id in event_ids
    assert event_b_id not in event_ids

    assert response.status_code == 200

    ids = {e["id"] for e in response.json}

    assert event_data["event_a"]["id"] in ids
    assert event_data["event_b"]["id"] not in ids
