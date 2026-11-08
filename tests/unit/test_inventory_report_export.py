
import csv
import io

from unittest.mock import patch

from app.services.inventory_report_export import (
    export_movement_report_csv,
)


def test_export_movement_report_csv():

    fake_report = {
        "items": [
            {
                "movement_id": 1,
                "reservation_id": 10,
                "inventory_item_id": 5,
                "event_id": 3,
                "sku": "TEST-001",
                "item_name": "Mesa redonda",
                "movement_type": "dispatch",
                "quantity": 8,
                "notes": None,
                "created_by": 1,
                "created_at": "2026-11-07T10:00:00Z",
            }
        ],
        "total": 1,
        "page": 1,
        "per_page": 1000,
        "pages": 1,
    }

    with patch(
        "app.services.inventory_report_export.get_movement_report",
        return_value=fake_report,
    ) as mock_report:

        content = export_movement_report_csv(
            tenant_id=1,
        )

    rows = list(
        csv.DictReader(io.StringIO(content))
    )

    assert len(rows) == 1
    assert rows[0]["SKU"] == "TEST-001"
    assert rows[0]["Cantidad"] == "8"
    assert rows[0]["Tipo Movimiento"] == "dispatch"

    mock_report.assert_called_once()
    assert mock_report.call_args.kwargs["tenant_id"] == 1
