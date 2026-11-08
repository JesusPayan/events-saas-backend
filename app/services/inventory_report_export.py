
from app.services.inventory_csv_export import build_csv

from app.services.inventory_export_columns import (
    MOVEMENT_EXPORT_COLUMNS,
    AVAILABILITY_EXPORT_COLUMNS,
)

from app.services.inventory_movement_reporting import (
    get_movement_report,
)

from app.services.inventory_reporting import (
    get_availability_report,
)
from app.services.inventory_excel_export import build_excel

EXPORT_PAGE_SIZE = 100
MAX_EXPORT_ROWS = 100_000


def export_movement_report_excel(
    tenant_id,
    date_from=None,
    date_to=None,
    event_id=None,
    item_id=None,
    movement_type=None,
):
    filters = {
        "tenant_id": tenant_id,
        "date_from": date_from,
        "date_to": date_to,
        "event_id": event_id,
        "item_id": item_id,
        "movement_type": movement_type,
    }

    rows = _collect_report_rows(
        get_movement_report,
        filters,
    )

    return build_excel(
        rows,
        MOVEMENT_EXPORT_COLUMNS,
        sheet_name="Movimientos",
    )


def export_availability_report_excel(
    tenant_id,
    starts_at,
    ends_at,
    category_id=None,
    item_id=None,
    search=None,
):
    filters = {
        "tenant_id": tenant_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "category_id": category_id,
        "item_id": item_id,
        "search": search,
    }

    rows = _collect_report_rows(
        get_availability_report,
        filters,
    )

    return build_excel(
        rows,
        AVAILABILITY_EXPORT_COLUMNS,
        sheet_name="Disponibilidad",
    )


def _collect_report_rows(report_function, filters):
    """
    Recupera todos los registros filtrados
    reutilizando el servicio de reportes.

    No limita la exportación a la página visible.
    """

    first_page = report_function(
        **filters,
        page=1,
        per_page=EXPORT_PAGE_SIZE,
    )

    total = first_page["total"]

    if total > MAX_EXPORT_ROWS:
        raise ValueError("export_limit_exceeded")

    rows = list(first_page["items"])

    for page in range(2, first_page["pages"] + 1):
        result = report_function(
            **filters,
            page=page,
            per_page=EXPORT_PAGE_SIZE,
        )

        rows.extend(result["items"])

    return rows


def export_movement_report_csv(
    tenant_id,
    date_from=None,
    date_to=None,
    event_id=None,
    item_id=None,
    movement_type=None,
):
    """
    Exporta movimientos de inventario a CSV.
    """

    filters = {
        "tenant_id": tenant_id,
        "date_from": date_from,
        "date_to": date_to,
        "event_id": event_id,
        "item_id": item_id,
        "movement_type": movement_type,
    }

    rows = _collect_report_rows(
        get_movement_report,
        filters,
    )

    return build_csv(
        rows,
        MOVEMENT_EXPORT_COLUMNS,
    )


def export_availability_report_csv(
    tenant_id,
    starts_at,
    ends_at,
    category_id=None,
    item_id=None,
    search=None,
):
    """
    Exporta disponibilidad de inventario a CSV.
    """

    filters = {
        "tenant_id": tenant_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "category_id": category_id,
        "item_id": item_id,
        "search": search,
    }

    rows = _collect_report_rows(
        get_availability_report,
        filters,
    )

    return build_csv(
        rows,
        AVAILABILITY_EXPORT_COLUMNS,
    )
