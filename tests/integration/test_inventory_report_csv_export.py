
from unittest.mock import patch

import pytest

import pytest
from unittest.mock import patch



@pytest.fixture
def auth_headers(test_context):
    return {
        "Authorization": f"Bearer {test_context['token']}",
        "X-Tenant-ID": str(test_context["tenant_id"]),
    }


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.mark.parametrize(
    "endpoint,export_function",
    [
        (
            "/api/v1/inventory/reports/movements/export",
            "export_movement_report_csv",
        ),
        (
            "/api/v1/inventory/reports/availability/export",
            "export_availability_report_csv",
        ),
    ],
)
def test_csv_export_requires_authentication(
    client,
    endpoint,
    export_function,
):
    response = client.get(endpoint)

    assert response.status_code in (401, 403)


def test_csv_export_movements_response(
    client,
    auth_headers,
):
    csv_content = "ID Movimiento,SKU\r\n1,TEST-001\r\n"

    with patch(
        "app.api.inventory.export_movement_report_csv",
        return_value=csv_content,
    ):
        response = client.get(
            "/api/v1/inventory/reports/movements/export",
            headers=auth_headers,
        )

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment" in response.headers["Content-Disposition"]

    assert "TEST-001" in response.get_data(as_text=True)


def test_csv_export_availability_response(
    client,
    auth_headers,
):
    csv_content = "SKU,Cantidad Disponible\r\nTEST-001,10\r\n"

    with patch(
        "app.api.inventory.export_availability_report_csv",
        return_value=csv_content,
    ):
        response = client.get(
            "/api/v1/inventory/reports/availability/export",
            query_string={
                "starts_at": "2026-11-07T10:00:00Z",
                "ends_at": "2026-11-08T10:00:00Z",
            },
            headers=auth_headers,
        )

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment" in response.headers["Content-Disposition"]

    assert "TEST-001" in response.get_data(as_text=True)
