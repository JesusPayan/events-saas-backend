
from datetime import date
from decimal import Decimal
from sqlalchemy import select

from app.extensions import db
from app.models.crm import Client
from app.models.event import Event
from app.models.inventory_item import InventoryItem
from app.services.quote_calculator import (
    calculate_item,
    QuoteCalculationError,
)


class QuoteValidationError(Exception):
    def __init__(self, details, status_code=400):
        super().__init__("quote_validation_error")
        self.details = details
        self.status_code = status_code


def positive_id(value):
    return type(value) is int and value > 0


def validate_quote(data, tenant_id):
    if not isinstance(data, dict):
        raise QuoteValidationError({"body": "invalid_json"})

    allowed = {
        "client_id", "event_id", "valid_until",
        "notes", "terms_conditions", "items"
    }
    errors = {
        key: "unknown_field"
        for key in data if key not in allowed
    }

    client_id = data.get("client_id")
    event_id = data.get("event_id")

    if not positive_id(client_id):
        errors["client_id"] = "invalid_id"

    if not positive_id(event_id):
        errors["event_id"] = "invalid_id"

    valid_until = None
    if data.get("valid_until") is not None:
        try:
            raw = data["valid_until"]
            if not isinstance(raw, str):
                raise ValueError()
            valid_until = date.fromisoformat(raw)
        except ValueError:
            errors["valid_until"] = "invalid_date"

    for field in ("notes", "terms_conditions"):
        value = data.get(field)
        if value is not None and not isinstance(value, str):
            errors[field] = "must_be_string"

    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        errors["items"] = "required_nonempty_list"
        raw_items = []
    elif len(raw_items) > 200:
        errors["items"] = "too_many_items"
        raw_items = []

    if errors:
        raise QuoteValidationError(errors)

    client = db.session.scalar(
        select(Client).where(
            Client.id == client_id,
            Client.tenant_id == tenant_id
        )
    )

    if client is None:
        raise QuoteValidationError(
            {"client_id": "not_found"}, 404
        )

    event = db.session.scalar(
        select(Event).where(
            Event.id == event_id,
            Event.tenant_id == tenant_id,
            Event.client_id == client_id
        )
    )

    if event is None:
        raise QuoteValidationError(
            {"event_id": "not_found_or_client_mismatch"},
            404
        )

    cleaned_items = []

    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            raise QuoteValidationError({
                f"items[{index}]": "invalid_object"
            })

        allowed_item = {
            "item_type", "inventory_item_id",
            "description", "quantity", "unit_price",
            "discount_amount", "tax_rate"
        }

        unknown = set(item) - allowed_item
        if unknown:
            raise QuoteValidationError({
                f"items[{index}]": "unknown_fields",
                "fields": sorted(unknown)
            })

        item_type = item.get("item_type")
        if item_type not in ("inventory", "service", "custom"):
            raise QuoteValidationError({
                f"items[{index}].item_type": "invalid_type"
            })

        inventory_item_id = item.get("inventory_item_id")

        if item_type == "inventory":
            if not positive_id(inventory_item_id):
                raise QuoteValidationError({
                    f"items[{index}].inventory_item_id": "invalid_id"
                })

            inventory_item = db.session.scalar(
                select(InventoryItem).where(
                    InventoryItem.id == inventory_item_id,
                    InventoryItem.tenant_id == tenant_id,
                    InventoryItem.is_active.is_(True)
                )
            )

            if inventory_item is None:
                raise QuoteValidationError({
                    f"items[{index}].inventory_item_id": "not_found"
                }, 404)
        elif inventory_item_id is not None:
            raise QuoteValidationError({
                f"items[{index}].inventory_item_id":
                    "only_allowed_for_inventory"
            })

        description = item.get("description")
        if (
            not isinstance(description, str)
            or not description.strip()
            or len(description.strip()) > 500
        ):
            raise QuoteValidationError({
                f"items[{index}].description": "invalid_description"
            })

        try:
            calculated = calculate_item(item)
        except (QuoteCalculationError, ArithmeticError) as exc:
            raise QuoteValidationError({
                f"items[{index}]": str(exc)
            }) from exc

        # Los artículos físicos se cotizan en unidades enteras.
        if (
            item_type == "inventory"
            and calculated["quantity"] % 1 != 0
        ):
            raise QuoteValidationError({
                f"items[{index}].quantity":
                    "integer_required_for_inventory"
            })

        # Proteger las precisiones de MySQL DECIMAL.
        limits = {
            "quantity": Decimal("9999999999.99"),
            "unit_price": Decimal("999999999999.99"),
            "discount_amount": Decimal("999999999999.99"),
            "subtotal": Decimal("999999999999.99"),
            "tax_amount": Decimal("999999999999.99"),
            "total": Decimal("999999999999.99"),
        }

        for field, limit in limits.items():
            if calculated[field] > limit:
                raise QuoteValidationError({
                    f"items[{index}].{field}": "amount_out_of_range"
                })

        if calculated["unit_price"] != Decimal(
            str(item["unit_price"])
        ):
            raise QuoteValidationError({
                f"items[{index}].unit_price":
                    "maximum_two_decimals"
            })

        rate = calculated["tax_rate"]
        if rate != rate.quantize(Decimal("0.0001")):
            raise QuoteValidationError({
                f"items[{index}].tax_rate":
                    "maximum_four_decimals"
            })

        cleaned_items.append({
            "item_type": item_type,
            "inventory_item_id": inventory_item_id,
            "description": description.strip(),
            **calculated,
            "sort_order": index
        })

    return {
        "client_id": client_id,
        "event_id": event_id,
        "valid_until": valid_until,
        "notes": data.get("notes"),
        "terms_conditions": data.get("terms_conditions"),
        "items": cleaned_items
    }
