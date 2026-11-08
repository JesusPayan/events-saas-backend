
from io import BytesIO

import pytest
import requests
from openpyxl import load_workbook

from test_inventory_full_lifecycle import lifecycle_scenario
from test_inventory_tenant_isolation import (
    restricted_inventory_user,
    two_tenant_inventory_scenario,
    unauthorized_tenant,
)

from app.services.inventory_export_columns import (
    MOVEMENT_EXPORT_COLUMNS,
    AVAILABILITY_EXPORT_COLUMNS,
)


MOVEMENTS_PATH = "/inventory/reports/movements"
AVAILABILITY_PATH = "/inventory/reports/availability"

EXCEL_MIMETYPE = (
    "application/vnd.openxmlformats-officedocument."
    "spreadsheetml.sheet"
)


def read_excel_response(response):
    assert response.status_code == 200, response.text
    assert response.headers["Content-Type"].startswith(
        EXCEL_MIMETYPE
    )
    assert "attachment" in response.headers.get(
        "Content-Disposition", ""
    )

    workbook = load_workbook(
        BytesIO(response.content),
        read_only=True,
        data_only=False,
    )
    sheet = workbook.active
    values = list(sheet.values)
    workbook.close()

    return values[0], values[1:]


@pytest.mark.parametrize(
    "path,columns,needs_dates",
    [
        (MOVEMENTS_PATH, MOVEMENT_EXPORT_COLUMNS, False),
        (AVAILABILITY_PATH, AVAILABILITY_EXPORT_COLUMNS, True),
    ],
)
def test_excel_matches_json_report(
    lifecycle_scenario,
    path,
    columns,
    needs_dates,
):
    s = lifecycle_scenario

    params = {"item_id": s["item_id"]}

    if needs_dates:
        params.update({
            "starts_at": s["starts_at"].isoformat() + "Z",
            "ends_at": s["ends_at"].isoformat() + "Z",
        })

    json_response = requests.get(
        f"{s['base_url']}{path}",
        headers=s["headers"],
        params={**params, "per_page": 100},
        timeout=45,
    )

    excel_response = requests.get(
        f"{s['base_url']}{path}/export.xlsx",
        headers=s["headers"],
        params=params,
        timeout=45,
    )

    assert json_response.status_code == 200, json_response.text

    report = json_response.json()
    headers, rows = read_excel_response(excel_response)

    assert list(headers) == [
        title for _, title in columns
    ]

    assert len(rows) == report["total"]
    assert report["total"] <= 100

    # Comparar valores por campo, independientemente
    # del orden de las filas.
    def normalized(value):
        return "" if value is None else str(value)

    expected = sorted([
        tuple(normalized(item.get(field)) for field, _ in columns)
        for item in report["items"]
    ])

    actual = sorted([
        tuple(normalized(value) for value in row)
        for row in rows
    ])

    assert actual == expected


@pytest.mark.parametrize(
    "path,params",
    [
        (MOVEMENTS_PATH, {"movement_type": "invalid"}),
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
def test_excel_rejects_invalid_filters(
    lifecycle_scenario,
    path,
    params,
):
    s = lifecycle_scenario

    response = requests.get(
        f"{s['base_url']}{path}/export.xlsx",
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
def test_excel_requires_inventory_read(
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
        f"{s['base_url']}{path}/export.xlsx",
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
def test_excel_rejects_unauthorized_tenant(
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
        f"{s['base_url']}{path}/export.xlsx",
        headers={
            "Authorization": f"Bearer {test_context['token']}",
            "X-Tenant-ID": str(unauthorized_tenant),
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
def test_excel_isolates_foreign_tenant(
    two_tenant_inventory_scenario,
    path,
    needs_dates,
):
    s = two_tenant_inventory_scenario

    params = {"item_id": s["item_b_id"]}

    if needs_dates:
        params.update({
            "starts_at": s["starts_at"].isoformat() + "Z",
            "ends_at": s["ends_at"].isoformat() + "Z",
        })

    response = requests.get(
        f"{s['base_url']}{path}/export.xlsx",
        headers=s["headers_a"],
        params=params,
        timeout=45,
    )

    headers, rows = read_excel_response(response)

    assert headers
    assert rows == []