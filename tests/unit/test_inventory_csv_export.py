
import csv
import io

from app.services.inventory_csv_export import build_csv


def test_build_csv_with_movements():
    rows = [
        {
            "movement_id": 1,
            "sku": "TEST-001",
            "quantity": 8,
        },
        {
            "movement_id": 2,
            "sku": "TEST-002",
            "quantity": 3,
        },
    ]

    columns = [
        ("movement_id", "ID Movimiento"),
        ("sku", "SKU"),
        ("quantity", "Cantidad"),
    ]

    content = build_csv(rows, columns)

    reader = csv.DictReader(io.StringIO(content))
    result = list(reader)

    assert len(result) == 2
    assert result[0]["SKU"] == "TEST-001"
    assert result[0]["Cantidad"] == "8"
    assert result[1]["Cantidad"] == "3"


def test_build_csv_without_rows():
    content = build_csv(
        [],
        [("sku", "SKU"), ("quantity", "Cantidad")],
    )

    assert content == "SKU,Cantidad\r\n"


def test_build_csv_escapes_formula_values():
    content = build_csv(
        [{"sku": "=1+1"}],
        [("sku", "SKU")],
    )

    assert "'=1+1" in content
