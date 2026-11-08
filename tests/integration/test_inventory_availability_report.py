
import requests

from test_inventory_full_lifecycle import lifecycle_scenario
from uuid import uuid4
from datetime import timedelta

from test_inventory_tenant_isolation import (
    restricted_inventory_user,
    two_tenant_inventory_scenario,
    unauthorized_tenant,
)
from tests.conftest import test_context


def test_report_requires_inventory_read_permission(
    lifecycle_scenario,
    restricted_inventory_user,
):
    s = lifecycle_scenario
    user = restricted_inventory_user

    response = requests.get(
        f"{s['base_url']}/inventory/reports/availability",
        headers={
            "Authorization": f"Bearer {user['token']}",
            "X-Tenant-ID": str(user["tenant_id"]),
        },
        params={
            "starts_at": s["starts_at"].isoformat() + "Z",
            "ends_at": s["ends_at"].isoformat() + "Z",
        },
        timeout=45,
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"] == "forbidden"


def test_report_cannot_expose_foreign_tenant_item(
    two_tenant_inventory_scenario,
):
    s = two_tenant_inventory_scenario

    response = requests.get(
        f"{s['base_url']}/inventory/reports/availability",
        headers=s["headers_a"],
        params={
            "starts_at": s["starts_at"].isoformat() + "Z",
            "ends_at": s["ends_at"].isoformat() + "Z",
            "item_id": s["item_b_id"],
        },
        timeout=45,
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["total"] == 0
    assert data["items"] == []


def test_report_rejects_tenant_without_membership(
    lifecycle_scenario,
    unauthorized_tenant,
    test_context,
):
    s = lifecycle_scenario

    response = requests.get(
        f"{s['base_url']}/inventory/reports/availability",
        headers={
            "Authorization": f"Bearer {test_context['token']}",
            "X-Tenant-ID": str(unauthorized_tenant),
        },
        params={
            "starts_at": s["starts_at"].isoformat() + "Z",
            "ends_at": s["ends_at"].isoformat() + "Z",
        },
        timeout=45,
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"] == "forbidden"


def test_availability_report_ignores_cancelled_reservation(
    lifecycle_scenario,
):
    s = lifecycle_scenario

    reservation_response = requests.post(
        f"{s['base_url']}/events/{s['event_id']}/reservations",
        headers={
            **s["headers"],
            "Idempotency-Key": f"report-{uuid4().hex}",
        },
        json={
            "inventory_item_id": s["item_id"],
            "quantity": 4,
        },
        timeout=45,
    )

    assert reservation_response.status_code == 201, (
        reservation_response.text
    )

    reservation_id = reservation_response.json()["id"]

    cancel_response = requests.patch(
        f"{s['base_url']}/events/{s['event_id']}"
        f"/reservations/{reservation_id}/cancel",
        headers=s["headers"],
        timeout=45,
    )

    assert cancel_response.status_code == 200, (
        cancel_response.text
    )

    report_response = requests.get(
        f"{s['base_url']}/inventory/reports/availability",
        headers=s["headers"],
        params={
            "starts_at": s["starts_at"].isoformat() + "Z",
            "ends_at": s["ends_at"].isoformat() + "Z",
            "item_id": s["item_id"],
        },
        timeout=45,
    )

    assert report_response.status_code == 200, (
        report_response.text
    )

    item = report_response.json()["items"][0]

    assert item["quantity_reserved"] == 0
    assert item["quantity_available"] == 10

def test_availability_report_without_date_overlap(
    lifecycle_scenario,
):
    s = lifecycle_scenario

    reservation = requests.post(
        f"{s['base_url']}/events/{s['event_id']}/reservations",
        headers={
            **s["headers"],
            "Idempotency-Key": f"report-{uuid4().hex}",
        },
        json={
            "inventory_item_id": s["item_id"],
            "quantity": 4,
        },
        timeout=45,
    )

    assert reservation.status_code == 201, reservation.text

    # Consultamos un periodo posterior al evento.
    starts_at = s["ends_at"] + timedelta(days=2)
    ends_at = starts_at + timedelta(hours=6)

    response = requests.get(
        f"{s['base_url']}/inventory/reports/availability",
        headers=s["headers"],
        params={
            "starts_at": starts_at.isoformat() + "Z",
            "ends_at": ends_at.isoformat() + "Z",
            "item_id": s["item_id"],
        },
        timeout=45,
    )

    assert response.status_code == 200, response.text

    item = response.json()["items"][0]

    assert item["quantity_reserved"] == 0
    assert item["quantity_available"] == 10


def test_availability_report_with_reservation(
    lifecycle_scenario,
):
    s = lifecycle_scenario

    # 1. Reservar cuatro unidades.
    reservation = requests.post(
        f"{s['base_url']}/events/"
        f"{s['event_id']}/reservations",
        headers={
            **s["headers"],
            "Idempotency-Key": f"report-{uuid4().hex}",
        },
        json={
            "inventory_item_id": s["item_id"],
            "quantity": 4,
        },
        timeout=45,
    )

    assert reservation.status_code == 201, reservation.text

    # 2. Consultar el reporte para el mismo periodo.
    response = requests.get(
        f"{s['base_url']}/inventory/reports/availability",
        headers=s["headers"],
        params={
            "starts_at": s["starts_at"].isoformat() + "Z",
            "ends_at": s["ends_at"].isoformat() + "Z",
            "item_id": s["item_id"],
        },
        timeout=45,
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["total"] == 1

    item = data["items"][0]

    assert item["quantity_total"] == 10
    assert item["quantity_reserved"] == 4
    assert item["quantity_available"] == 6
    assert item["inventory_shortage"] == 0
def test_availability_report_without_reservations(
    lifecycle_scenario,
):
    s = lifecycle_scenario

    response = requests.get(
        f"{s['base_url']}/inventory/reports/availability",
        headers=s["headers"],
        params={
            "starts_at": s["starts_at"].isoformat() + "Z",
            "ends_at": s["ends_at"].isoformat() + "Z",
            "item_id": s["item_id"],
        },
        timeout=45,
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["total"] == 1
    assert len(data["items"]) == 1

    item = data["items"][0]

    assert item["inventory_item_id"] == s["item_id"]
    assert item["quantity_total"] == 10
    assert item["quantity_unavailable"] == 0
    assert item["quantity_rentable"] == 10
    assert item["quantity_reserved"] == 0
    assert item["quantity_available"] == 10
    assert item["inventory_shortage"] == 0


import pytest


@pytest.mark.parametrize(
    "params",
    [
        {},
        {
            "starts_at": "2026-11-15T10:00:00Z",
        },
        {
            "starts_at": "fecha-invalida",
            "ends_at": "2026-11-15T20:00:00Z",
        },
        {
            "starts_at": "2026-11-15T20:00:00Z",
            "ends_at": "2026-11-15T10:00:00Z",
        },
        {
            "starts_at": "2026-11-15T10:00:00Z",
            "ends_at": "2026-11-15T20:00:00Z",
            "page": 0,
        },
        {
            "starts_at": "2026-11-15T10:00:00Z",
            "ends_at": "2026-11-15T20:00:00Z",
            "per_page": 101,
        },
        {
            "starts_at": "2026-11-15T10:00:00Z",
            "ends_at": "2026-11-15T20:00:00Z",
            "category_id": -1,
        },
        {
            "starts_at": "2026-11-15T10:00:00",
            "ends_at": "2026-11-15T20:00:00",
        },
    ],
)
def test_availability_report_rejects_invalid_parameters(
    lifecycle_scenario,
    params,
):
    s = lifecycle_scenario

    response = requests.get(
        f"{s['base_url']}/inventory/reports/availability",
        headers=s["headers"],
        params=params,
        timeout=45,
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"] == "validation_error"


def test_availability_report_filters_and_pagination(
    lifecycle_scenario,
):
    s = lifecycle_scenario

    base_params = {
        "starts_at": s["starts_at"].isoformat() + "Z",
        "ends_at": s["ends_at"].isoformat() + "Z",
    }

    # Filtrar por ID de artículo.
    response = requests.get(
        f"{s['base_url']}/inventory/reports/availability",
        headers=s["headers"],
        params={
            **base_params,
            "item_id": s["item_id"],
            "page": 1,
            "per_page": 1,
        },
        timeout=45,
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["total"] == 1
    assert data["page"] == 1
    assert data["per_page"] == 1
    assert data["pages"] == 1
    assert len(data["items"]) == 1

    # Buscar por un SKU inexistente.
    response = requests.get(
        f"{s['base_url']}/inventory/reports/availability",
        headers=s["headers"],
        params={
            **base_params,
            "search": "SKU-INEXISTENTE-XYZ-999",
        },
        timeout=45,
    )

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0
    assert response.json()["items"] == []

def test_availability_report_requires_authentication(
    lifecycle_scenario,
):
    s = lifecycle_scenario

    response = requests.get(
        f"{s['base_url']}/inventory/reports/availability",
        headers={
            "X-Tenant-ID": str(s["tenant_id"]),
        },
        params={
            "starts_at": s["starts_at"].isoformat() + "Z",
            "ends_at": s["ends_at"].isoformat() + "Z",
        },
        timeout=45,
    )

    assert response.status_code == 401, response.text

def test_availability_report_does_not_expose_other_items(
    lifecycle_scenario,
):
    s = lifecycle_scenario

    response = requests.get(
        f"{s['base_url']}/inventory/reports/availability",
        headers=s["headers"],
        params={
            "starts_at": s["starts_at"].isoformat() + "Z",
            "ends_at": s["ends_at"].isoformat() + "Z",
            "item_id": 999999999999,
        },
        timeout=45,
    )

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0
    assert response.json()["items"] == []
