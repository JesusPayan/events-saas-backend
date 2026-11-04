
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, g

from app.security import tenant_permission

from app.services.inventory_operations import (
    get_operations,
    get_operations_summary
)


bp = Blueprint(
    "inventory_operations",
    __name__
)


def parse_utc_datetime(value, field):
    if value is None:
        return None

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except (ValueError, TypeError, AttributeError):
        raise ValueError(
            f"invalid_{field}_datetime"
        )

    if parsed.tzinfo is None:
        raise ValueError(
            f"{field}_timezone_required"
        )

    return parsed.astimezone(
        timezone.utc
    ).replace(tzinfo=None)


def parse_positive_int(
    value,
    field,
    default=None
):
    if value is None:
        return default

    try:
        parsed = int(value)
    except (ValueError, TypeError):
        raise ValueError(
            f"invalid_{field}"
        )

    if parsed <= 0:
        raise ValueError(
            f"invalid_{field}"
        )

    return parsed


def parse_filters():

    date_from = parse_utc_datetime(
        request.args.get("from"),
        "from"
    )

    date_to = parse_utc_datetime(
        request.args.get("to"),
        "to"
    )

    if (
        date_from is not None
        and date_to is not None
        and date_to <= date_from
    ):
        raise ValueError(
            "invalid_date_range"
        )

    page = parse_positive_int(
        request.args.get("page"),
        "page",
        1
    )

    per_page = parse_positive_int(
        request.args.get("per_page"),
        "per_page",
        50
    )

    if per_page > 100:
        raise ValueError(
            "per_page_exceeds_limit"
        )

    return {
        "date_from": date_from,
        "date_to": date_to,
        "event_id": parse_positive_int(
            request.args.get("event_id"),
            "event_id"
        ),
        "item_id": parse_positive_int(
            request.args.get("item_id"),
            "item_id"
        ),
        "page": page,
        "per_page": per_page
    }


def operations_response(status="all"):
    try:
        filters = parse_filters()

        result = get_operations(
            tenant_id=g.tenant_id,
            status=status,
            **filters
        )

        return jsonify(result), 200

    except ValueError as exc:
        return jsonify(
            error=str(exc)
        ), 400


@bp.get("/inventory/operations/calendar")
@tenant_permission("inventory.read")
def calendar():
    return operations_response(
        status="all"
    )


@bp.get("/inventory/operations/pending-dispatches")
@tenant_permission("inventory.read")
def pending_dispatches():
    return operations_response(
        status="pending_dispatch"
    )


@bp.get("/inventory/operations/pending-returns")
@tenant_permission("inventory.read")
def pending_returns():

    overdue = request.args.get(
        "overdue",
        "false"
    ).lower()

    if overdue not in (
        "true",
        "false"
    ):
        return jsonify(
            error="invalid_overdue"
        ), 400

    status = (
        "overdue_return"
        if overdue == "true"
        else "pending_return"
    )

    return operations_response(
        status=status
    )


@bp.get("/inventory/operations/summary")
@tenant_permission("inventory.read")
def summary():
    try:
        date_from = parse_utc_datetime(
            request.args.get("from"),
            "from"
        )

        date_to = parse_utc_datetime(
            request.args.get("to"),
            "to"
        )

        if (
            date_from is not None
            and date_to is not None
            and date_to <= date_from
        ):
            raise ValueError(
                "invalid_date_range"
            )

        result = get_operations_summary(
            tenant_id=g.tenant_id,
            date_from=date_from,
            date_to=date_to
        )

        return jsonify(result), 200

    except ValueError as exc:
        return jsonify(
            error=str(exc)
        ), 400
