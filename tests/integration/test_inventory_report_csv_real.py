
import csv
import io

import pytest
import requests

from test_inventory_full_lifecycle import lifecycle_scenario

from test_inventory_tenant_isolation import (
    restricted_inventory_user,
    two_tenant_inventory_scenario,
    unauthorized_tenant,
)


MOVEMENTS_PATH = "/inventory/reports/movements"
AVAILABILITY_PATH = "/inventory/reports/availability"


def read_csv_response(response):
    assert response.status_code == 200, response.text

    assert response.headers["Content-Type"].startswith(
        "text/csv"
    )

    assert "attachment" in response.headers.get(
        "Content-Disposition", ""
    )

    content = response.content.decode("utf-8-sig")

    return list(csv.DictReader(io.StringIO(content)))


def test_movement_csv_matches_json_report(lifecycle_scenario):
    s = lifecycle_scenario

    params = {
        "event_id": s["event_id"],
    }

    json_response = requests.get(
        f"{s['base_url']}{MOVEMENTS_PATH}",
        headers=s["headers"],
        params={**params, "per_page": 100},
        timeout=45,
    )

    csv_response = requests.get(
        f"{s['base_url']}{MOVEMENTS_PATH}/export",
        headers=s["headers"],
        params=params,
        timeout=45,
    )

    assert json_response.status_code == 200, json_response.text

    json_data = json_response.json()
    csv_rows = read_csv_response(csv_response)

    assert len(csv_rows) == json_data["total"]

    json_ids = {
        str(item["movement_id"])
        for item in json_data["items"]
    }

    csv_ids = {
        row["ID Movimiento"]
        for row in csv_rows
    }

    assert json_ids == csv_ids


def test_availability_csv_matches_json_report(lifecycle_scenario):
    s = lifecycle_scenario

    params = {
        "starts_at": s["starts_at"].isoformat() + "Z",
        "ends_at": s["ends_at"].isoformat() + "Z",
        "item_id": s["item_id"],
    }

    json_response = requests.get(
        f"{s['base_url']}{AVAILABILITY_PATH}",
        headers=s["headers"],
        params=params,
        timeout=45,
    )

    csv_response = requests.get(
        f"{s['base_url']}{AVAILABILITY_PATH}/export",
        headers=s["headers"],
        params=params,
        timeout=45,
    )

    assert json_response.status_code == 200, json_response.text

    json_data = json_response.json()
    csv_rows = read_csv_response(csv_response)

    assert len(csv_rows) == json_data["total"]

    if json_data["items"]:
        expected = json_data["items"][0]
        actual = csv_rows[0]

        assert actual["SKU"] == expected["sku"]
        assert int(actual["Cantidad Total"]) == (
            expected["quantity_total"]
        )
        assert int(actual["Cantidad Disponible"]) == (
            expected["quantity_available"]
        )


@pytest.mark.parametrize(
    "path,params",
    [
        (
            MOVEMENTS_PATH,
            {"movement_type": "invalid"},
        ),
        (
            MOVEMENTS_PATH,
            {
                "date_from": "2026-11-08T10:00:00Z",
                "date_to": "2026-11-07T10:00:00Z",
            },
        ),
        (
            AVAILABILITY_PATH,
            {
                "starts_at": "2026-11-08T10:00:00Z",
                "ends_at": "2026-11-07T10:00:00Z",
            },
        ),
    ],
)
def test_csv_export_rejects_invalid_filters(
    lifecycle_scenario,
    path,
    params,
):
    s = lifecycle_scenario

    response = requests.get(
        f"{s['base_url']}{path}/export",
        headers=s["headers"],
        params=params,
        timeout=45,
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"] == "validation_error"


@pytest.mark.parametrize(
    "path,needs_dates",
    [
        (MOVEMENTS_PATH, False),
        (AVAILABILITY_PATH, True),
    ],
)
def test_csv_export_requires_inventory_read(
    lifecycle_scenario,
    restricted_inventory_user,
    path,
    needs_dates,
):
    s = lifecycle_scenario
    user = restricted_inventory_user

    params = {}

    if needs_dates:
        params = {
            "starts_at": s["starts_at"].isoformat() + "Z",
            "ends_at": s["ends_at"].isoformat() + "Z",
        }

    response = requests.get(
        f"{s['base_url']}{path}/export",
        headers={
            "Authorization": f"Bearer {user['token']}",
            "X-Tenant-ID": str(user["tenant_id"]),
        },
        params=params,
        timeout=45,
    )

    assert response.status_code == 403, response.text


@pytest.mark.parametrize(
    "path,needs_dates",
    [
        (MOVEMENTS_PATH, False),
        (AVAILABILITY_PATH, True),
    ],
)
def test_csv_export_rejects_unauthorized_tenant(
    lifecycle_scenario,
    unauthorized_tenant,
    test_context,
    path,
    needs_dates,
):
    s = lifecycle_scenario

    params = {}

    if needs_dates:
        params = {
            "starts_at": s["starts_at"].isoformat() + "Z",
            "ends_at": s["ends_at"].isoformat() + "Z",
        }

    response = requests.get(
        f"{s['base_url']}{path}/export",
        headers={
            "Authorization": f"Bearer {test_context['token']}",
            "X-Tenant-ID": str(unauthorized_tenant),
        },
        params=params,
        timeout=45,
    )

    assert response.status_code == 403, response.text


@pytest.mark.parametrize(
    "path,params_key",
    [
        (MOVEMENTS_PATH, "item_id"),
        (AVAILABILITY_PATH, "item_id"),
    ],
)
def test_csv_export_isolates_foreign_tenant(
    two_tenant_inventory_scenario,
    path,
    params_key,
):
    s = two_tenant_inventory_scenario

    params = {
        params_key: s["item_b_id"],
    }

    if path == AVAILABILITY_PATH:
        params.update({
            "starts_at": s["starts_at"].isoformat() + "Z",
            "ends_at": s["ends_at"].isoformat() + "Z",
        })

    response = requests.get(
        f"{s['base_url']}{path}/export",
        headers=s["headers_a"],
        params=params,
        timeout=45,
    )

    rows = read_csv_response(response)

    assert rows == []
