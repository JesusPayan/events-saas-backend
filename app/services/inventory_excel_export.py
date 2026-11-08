
from datetime import datetime, timezone
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter


DANGEROUS_PREFIXES = ("=", "+", "-", "@")


def _safe_value(value):
    """Evita interpretar texto no confiable como fórmula."""
    if value is None:
        return ""

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value

    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(
                tzinfo=None
            )
        return value

    text = str(value)

    if text.lstrip().startswith(DANGEROUS_PREFIXES):
        return "'" + text

    return text


def build_excel(rows, columns, sheet_name="Reporte"):
    """
    Genera un archivo XLSX en memoria.

    rows: lista de diccionarios
    columns: lista de (campo, encabezado)

    Retorna bytes del archivo Excel.
    """
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_name

    headers = [header for _, header in columns]
    worksheet.append(headers)

    header_fill = PatternFill(
        fill_type="solid",
        fgColor="17365D",
    )

    header_font = Font(
        bold=True,
        color="FFFFFF",
    )

    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(
            horizontal="center",
            vertical="center",
        )

    worksheet.row_dimensions[1].height = 25

    for row in rows:
        worksheet.append([
            _safe_value(row.get(field))
            for field, _ in columns
        ])

    for column_index, (_, header) in enumerate(
        columns,
        start=1,
    ):
        letter = get_column_letter(column_index)

        max_length = len(header)

        for cells in worksheet.iter_cols(
            min_col=column_index,
            max_col=column_index,
            min_row=2,
        ):
            for cell in cells:
                if cell.value is not None:
                    max_length = max(
                        max_length,
                        len(str(cell.value)),
                    )

        worksheet.column_dimensions[letter].width = min(
            max(max_length + 3, 14),
            45,
        )

    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions

    output = BytesIO()
    workbook.save(output)

    return output.getvalue()
