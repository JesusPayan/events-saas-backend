
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify, g
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.inventory_item import InventoryItem
from app.models.inventory_category import InventoryCategory
from app.security import tenant_permission
from app.services.inventory_movement_reporting import (
    get_movement_report,
)
from datetime import datetime, timezone

from app.services.inventory_reporting import get_availability_report
from flask import Response

from datetime import datetime, timezone
from flask import Response

from app.services.inventory_report_export import (
    export_movement_report_csv,
    export_availability_report_csv,
)


from flask import Response, g, jsonify, request
from datetime import datetime, timezone

from app.services.inventory_report_export import (
    export_movement_report_excel,
    export_availability_report_excel,
)
bp = Blueprint("inventory", __name__)

ALLOWED_FIELDS = {
    "category_id", "sku", "name", "description",
    "item_type", "quantity_total", "unit",
    "replacement_cost", "rental_price"
}

@bp.get("/inventory/reports/movements/export")
@tenant_permission("inventory.read")
def inventory_movement_report_export():
    try:
        raw_from = request.args.get("date_from")
        raw_to = request.args.get("date_to")

        date_from = (
            parse_report_datetime(raw_from)
            if raw_from is not None
            else None
        )

        date_to = (
            parse_report_datetime(raw_to)
            if raw_to is not None
            else None
        )

        event_id = parse_positive_int("event_id")
        item_id = parse_positive_int("item_id")

        movement_type = request.args.get("movement_type")

        csv_content = export_movement_report_csv(
            tenant_id=g.tenant_id,
            date_from=date_from,
            date_to=date_to,
            event_id=event_id,
            item_id=item_id,
            movement_type=movement_type,
        )

        filename = (
            "inventory_movements_"
            + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            + ".csv"
        )

        return Response(
            "\ufeff" + csv_content,
            status=200,
            mimetype="text/csv",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{filename}"'
                ),
                "Cache-Control": "no-store",
            },
        )

    except ValueError as exc:
        return jsonify(
            error="validation_error",
            detail=str(exc),
        ), 400

@bp.get("/inventory/reports/availability/export")
@tenant_permission("inventory.read")
def inventory_availability_report_export():
    try:
        starts_at = parse_report_datetime(
            request.args.get("starts_at")
        )

        ends_at = parse_report_datetime(
            request.args.get("ends_at")
        )

        category_id = parse_positive_int("category_id")
        item_id = parse_positive_int("item_id")

        search = request.args.get("search", "").strip()

        if len(search) > 180:
            raise ValueError("invalid_search")

        csv_content = export_availability_report_csv(
            tenant_id=g.tenant_id,
            starts_at=starts_at,
            ends_at=ends_at,
            category_id=category_id,
            item_id=item_id,
            search=search,
        )

        filename = (
            "inventory_availability_"
            + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            + ".csv"
        )

        return Response(
            "\ufeff" + csv_content,
            status=200,
            mimetype="text/csv",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{filename}"'
                ),
                "Cache-Control": "no-store",
            },
        )

    except ValueError as exc:
        return jsonify(
            error="validation_error",
            detail=str(exc),
        ), 400



def validate_item(data, partial=False):
    if not isinstance(data, dict):
        return {}, {"body": "invalid_json"}

    errors = {}
    cleaned = {}

    for field in data:
        if field not in ALLOWED_FIELDS:
            errors[field] = "unknown_field"

    for field in ALLOWED_FIELDS.intersection(data):
        value = data[field]

        if field == "category_id":
            if value is None:
                cleaned[field] = None
            elif (
                type(value) is not int
                or value <= 0
            ):
                errors[field] = "invalid_category"
            else:
                cleaned[field] = value
            continue

        if field == "quantity_total":
            if type(value) is not int or value < 0:
                errors[field] = "invalid_quantity"
            else:
                cleaned[field] = value
            continue

        if field in ("replacement_cost", "rental_price"):
            if value is None:
                cleaned[field] = None
                continue

            if isinstance(value, bool) or not isinstance(
                value, (str, int, float)
            ):
                errors[field] = "invalid_price"
                continue

            try:
                amount = Decimal(str(value))
                if (
                    not amount.is_finite()
                    or amount < 0
                    or amount > Decimal("9999999999.99")
                    or amount.as_tuple().exponent < -2
                ):
                    raise ValueError()

                cleaned[field] = amount
            except (InvalidOperation, ValueError):
                errors[field] = "invalid_price"
            continue

        if value is not None and not isinstance(value, str):
            errors[field] = "must_be_string"
            continue

        if isinstance(value, str):
            value = value.strip()

        cleaned[field] = value

    lengths = {
        "sku": 60,
        "name": 180,
        "unit": 30,
        "item_type": 20
    }

    for field, limit in lengths.items():
        if field in cleaned and cleaned[field] is not None:
            if len(cleaned[field]) > limit:
                errors[field] = "too_long"

    if "item_type" in cleaned:
        if cleaned["item_type"] not in ("product", "service"):
            errors["item_type"] = "invalid_type"

    if not partial:
        for field in ("sku", "name"):
            if not cleaned.get(field):
                errors[field] = "required"

    for field in ("sku", "name", "unit", "item_type"):
        if field in cleaned and not cleaned[field]:
            errors[field] = "required"

    return cleaned, errors


def get_item(item_id):
    return db.session.scalar(
        select(InventoryItem).where(
            InventoryItem.id == item_id,
            InventoryItem.tenant_id == g.tenant_id
        )
    )


def category_exists(category_id):
    if category_id is None:
        return True

    return db.session.scalar(
        select(InventoryCategory.id).where(
            InventoryCategory.id == category_id,
            InventoryCategory.tenant_id == g.tenant_id,
            InventoryCategory.is_active.is_(True)
        )
    ) is not None


@bp.get("/inventory/categories")
@tenant_permission("inventory.read")
def list_categories():
    categories = db.session.scalars(
        select(InventoryCategory)
        .where(
            InventoryCategory.tenant_id == g.tenant_id,
            InventoryCategory.is_active.is_(True)
        )
        .order_by(InventoryCategory.name)
    ).all()

    return jsonify([category.to_dict() for category in categories])


@bp.get("/inventory/items")
@tenant_permission("inventory.read")
def list_items():
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(
        100,
        max(1, request.args.get("per_page", 20, type=int))
    )

    search = request.args.get("search", "").strip()

    stmt = select(InventoryItem).where(
        InventoryItem.tenant_id == g.tenant_id
    )

    if search:
        stmt = stmt.where(
            InventoryItem.name.ilike(f"%{search}%")
            | InventoryItem.sku.ilike(f"%{search}%")
        )

    result = db.paginate(
        stmt.order_by(InventoryItem.id.desc()),
        page=page,
        per_page=per_page,
        error_out=False
    )

    return jsonify({
        "items": [item.to_dict() for item in result.items],
        "total": result.total,
        "page": result.page,
        "per_page": result.per_page,
        "pages": result.pages
    })


@bp.post("/inventory/items")
@tenant_permission("inventory.create")
def create_item():
    cleaned, errors = validate_item(
        request.get_json(silent=True)
    )

    if errors:
        return jsonify(error="validation_error", details=errors), 400

    if not category_exists(cleaned.get("category_id")):
        return jsonify(error="category_not_found"), 404

    item = InventoryItem(
        tenant_id=g.tenant_id,
        **cleaned
    )

    try:
        db.session.add(item)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(error="duplicate_sku_or_invalid_reference"), 409

    return jsonify(item.to_dict()), 201


@bp.get("/inventory/items/<int:item_id>")
@tenant_permission("inventory.read")
def get_inventory_item(item_id):
    item = get_item(item_id)

    if not item:
        return jsonify(error="not_found"), 404

    return jsonify(item.to_dict())


@bp.patch("/inventory/items/<int:item_id>")
@tenant_permission("inventory.update")
def update_inventory_item(item_id):
    item = get_item(item_id)

    if not item:
        return jsonify(error="not_found"), 404

    cleaned, errors = validate_item(
        request.get_json(silent=True),
        partial=True
    )

    if errors:
        return jsonify(error="validation_error", details=errors), 400

    if (
        "category_id" in cleaned
        and not category_exists(cleaned["category_id"])
    ):
        return jsonify(error="category_not_found"), 404

    for field, value in cleaned.items():
        setattr(item, field, value)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(error="duplicate_sku_or_invalid_reference"), 409

    return jsonify(item.to_dict())


@bp.patch("/inventory/items/<int:item_id>/deactivate")
@tenant_permission("inventory.update")
def deactivate_inventory_item(item_id):
    item = get_item(item_id)

    if not item:
        return jsonify(error="not_found"), 404

    item.is_active = False
    db.session.commit()

    return jsonify(item.to_dict())


def validate_category(data, partial=False):
    if not isinstance(data, dict):
        return {}, {"body": "invalid_json"}

    allowed = {"name", "description"}
    cleaned = {}
    errors = {}

    for field in data:
        if field not in allowed:
            errors[field] = "unknown_field"

    for field in allowed.intersection(data):
        value = data[field]

        if value is not None and not isinstance(value, str):
            errors[field] = "must_be_string"
            continue

        if isinstance(value, str):
            value = value.strip()

        limit = 120 if field == "name" else 255

        if value is not None and len(value) > limit:
            errors[field] = "too_long"
            continue

        cleaned[field] = value

    if not partial and not cleaned.get("name"):
        errors["name"] = "required"

    if "name" in cleaned and not cleaned["name"]:
        errors["name"] = "required"

    return cleaned, errors


def get_category(category_id):
    return db.session.scalar(
        select(InventoryCategory).where(
            InventoryCategory.id == category_id,
            InventoryCategory.tenant_id == g.tenant_id
        )
    )


@bp.post("/inventory/categories")
@tenant_permission("inventory.create")
def create_category():
    cleaned, errors = validate_category(
        request.get_json(silent=True)
    )

    if errors:
        return jsonify(
            error="validation_error",
            details=errors
        ), 400

    category = InventoryCategory(
        tenant_id=g.tenant_id,
        **cleaned
    )

    try:
        db.session.add(category)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(error="duplicate_category"), 409

    return jsonify(category.to_dict()), 201


@bp.get("/inventory/categories/<int:category_id>")
@tenant_permission("inventory.read")
def get_inventory_category(category_id):
    category = get_category(category_id)

    if not category:
        return jsonify(error="not_found"), 404

    return jsonify(category.to_dict())


@bp.patch("/inventory/categories/<int:category_id>")
@tenant_permission("inventory.update")
def update_category(category_id):
    category = get_category(category_id)

    if not category:
        return jsonify(error="not_found"), 404

    cleaned, errors = validate_category(
        request.get_json(silent=True),
        partial=True
    )

    if errors:
        return jsonify(
            error="validation_error",
            details=errors
        ), 400

    for field, value in cleaned.items():
        setattr(category, field, value)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(error="duplicate_category"), 409

    return jsonify(category.to_dict())


@bp.patch("/inventory/categories/<int:category_id>/deactivate")
@tenant_permission("inventory.update")
def deactivate_category(category_id):
    category = get_category(category_id)

    if not category:
        return jsonify(error="not_found"), 404

    category.is_active = False
    db.session.commit()

    return jsonify(category.to_dict())

def parse_report_datetime(value):
    if not value:
        raise ValueError("date_range_required")

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("invalid_datetime") from exc

    if parsed.tzinfo is None:
        raise ValueError("timezone_required")

    return parsed.astimezone(
        timezone.utc
    ).replace(tzinfo=None)


def parse_positive_int(name, default=None, maximum=None):
    raw = request.args.get(name)

    if raw is None:
        return default

    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid_{name}") from exc

    if value <= 0 or (maximum is not None and value > maximum):
        raise ValueError(f"invalid_{name}")

    return value


@bp.get("/inventory/reports/availability")
@tenant_permission("inventory.read")
def inventory_availability_report():
    try:
        starts_at = parse_report_datetime(
            request.args.get("starts_at")
        )
        ends_at = parse_report_datetime(
            request.args.get("ends_at")
        )

        category_id = parse_positive_int("category_id")
        item_id = parse_positive_int("item_id")
        page = parse_positive_int("page", default=1)
        per_page = parse_positive_int(
            "per_page", default=20, maximum=100
        )

        search = request.args.get("search", "").strip()

        if len(search) > 180:
            raise ValueError("invalid_search")

        result = get_availability_report(
            tenant_id=g.tenant_id,
            starts_at=starts_at,
            ends_at=ends_at,
            category_id=category_id,
            item_id=item_id,
            search=search,
            page=page,
            per_page=per_page,
        )

        return jsonify(result), 200

    except ValueError as exc:
        return jsonify(
            error="validation_error",
            detail=str(exc),
        ), 400



@bp.get("/inventory/reports/movements")
@tenant_permission("inventory.read")
def inventory_movement_report():
    try:
        raw_from = request.args.get("date_from")
        raw_to = request.args.get("date_to")

        date_from = (
            parse_report_datetime(raw_from)
            if raw_from is not None
            else None
        )

        date_to = (
            parse_report_datetime(raw_to)
            if raw_to is not None
            else None
        )

        event_id = parse_positive_int("event_id")
        item_id = parse_positive_int("item_id")
        page = parse_positive_int("page", default=1)
        per_page = parse_positive_int(
            "per_page",
            default=20,
            maximum=100,
        )

        movement_type = request.args.get("movement_type")

        result = get_movement_report(
            tenant_id=g.tenant_id,
            date_from=date_from,
            date_to=date_to,
            event_id=event_id,
            item_id=item_id,
            movement_type=movement_type,
            page=page,
            per_page=per_page,
        )

        return jsonify(result), 200

    except ValueError as exc:
        return jsonify(
            error="validation_error",
            detail=str(exc),
        ), 400

EXCEL_MIMETYPE = (
    "application/vnd.openxmlformats-officedocument."
    "spreadsheetml.sheet"
)


@bp.get("/inventory/reports/movements/export.xlsx")
@tenant_permission("inventory.read")
def inventory_movement_report_excel_export():
    try:
        raw_from = request.args.get("date_from")
        raw_to = request.args.get("date_to")

        date_from = (
            parse_report_datetime(raw_from)
            if raw_from is not None
            else None
        )

        date_to = (
            parse_report_datetime(raw_to)
            if raw_to is not None
            else None
        )

        event_id = parse_positive_int("event_id")
        item_id = parse_positive_int("item_id")

        movement_type = request.args.get("movement_type")

        content = export_movement_report_excel(
            tenant_id=g.tenant_id,
            date_from=date_from,
            date_to=date_to,
            event_id=event_id,
            item_id=item_id,
            movement_type=movement_type,
        )

        timestamp = datetime.now(
            timezone.utc
        ).strftime("%Y%m%d_%H%M%S")

        return Response(
            content,
            status=200,
            mimetype=EXCEL_MIMETYPE,
            headers={
                "Content-Disposition": (
                    'attachment; filename='
                    f'"inventory_movements_{timestamp}.xlsx"'
                ),
                "Cache-Control": "no-store",
            },
        )

    except ValueError as exc:
        return jsonify(
            error="validation_error",
            detail=str(exc),
        ), 400


@bp.get("/inventory/reports/availability/export.xlsx")
@tenant_permission("inventory.read")
def inventory_availability_report_excel_export():
    try:
        starts_at = parse_report_datetime(
            request.args.get("starts_at")
        )

        ends_at = parse_report_datetime(
            request.args.get("ends_at")
        )

        category_id = parse_positive_int("category_id")
        item_id = parse_positive_int("item_id")

        search = request.args.get(
            "search", ""
        ).strip()

        if len(search) > 180:
            raise ValueError("invalid_search")

        content = export_availability_report_excel(
            tenant_id=g.tenant_id,
            starts_at=starts_at,
            ends_at=ends_at,
            category_id=category_id,
            item_id=item_id,
            search=search,
        )

        timestamp = datetime.now(
            timezone.utc
        ).strftime("%Y%m%d_%H%M%S")

        return Response(
            content,
            status=200,
            mimetype=EXCEL_MIMETYPE,
            headers={
                "Content-Disposition": (
                    'attachment; filename='
                    f'"inventory_availability_{timestamp}.xlsx"'
                ),
                "Cache-Control": "no-store",
            },
        )

    except ValueError as exc:
        return jsonify(
            error="validation_error",
            detail=str(exc),
        ), 400
