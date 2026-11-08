
from io import BytesIO

from openpyxl import load_workbook

from app.services.inventory_excel_export import build_excel


def open_excel(content):
    return load_workbook(BytesIO(content))


def test_excel_contains_headers_and_rows():
    columns = [
        ("sku", "SKU"),
        ("quantity", "Cantidad"),
    ]

    rows = [
        {"sku": "SILLA-001", "quantity": 15},
        {"sku": "MESA-002", "quantity": 20},
    ]

    workbook = open_excel(
        build_excel(
            rows,
            columns,
            sheet_name="Inventario",
        )
    )

    sheet = workbook["Inventario"]

    assert sheet["A1"].value == "SKU"
    assert sheet["B1"].value == "Cantidad"

    assert sheet["A2"].value == "SILLA-001"
    assert sheet["B2"].value == 15

    assert sheet["A3"].value == "MESA-002"
    assert sheet["B3"].value == 20

    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:B3"


def test_excel_without_rows():
    content = build_excel(
        [],
        [("sku", "SKU")],
    )

    workbook = open_excel(content)
    sheet = workbook.active

    assert sheet.max_row == 1
    assert sheet["A1"].value == "SKU"


def test_excel_prevents_formula_injection():
    content = build_excel(
        [
            {"name": "=1+1"},
            {"name": "+SUM(A1:A2)"},
        ],
        [("name", "Nombre")],
    )

    workbook = open_excel(content)
    sheet = workbook.active

    assert sheet["A2"].data_type != "f"
    assert sheet["A3"].data_type != "f"

    assert sheet["A2"].value == "'=1+1"
    assert sheet["A3"].value == "'+SUM(A1:A2)"


def test_excel_preserves_numeric_values():
    content = build_excel(
        [{"quantity": 25}],
        [("quantity", "Cantidad")],
    )

    workbook = open_excel(content)

    assert workbook.active["A2"].value == 25
    assert workbook.active["A2"].data_type == "n"
