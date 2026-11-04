
from datetime import datetime, timezone

ALLOWED_FIELDS = {
    "client_id", "name", "event_type", "description",
    "starts_at", "ends_at", "location", "estimated_guests"
}

MAX_LENGTHS = {
    "name": 180,
    "event_type": 50,
    "location": 255
}


def parse_datetime(value):
    if not isinstance(value, str):
        raise ValueError("invalid_datetime")

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid_datetime")

    if dt.tzinfo is None:
        raise ValueError("timezone_required")

    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def validate_event(data, partial=False):
    if not isinstance(data, dict):
        return {}, {"body": "invalid_json"}

    cleaned = {}
    errors = {}

    for field in data:
        if field not in ALLOWED_FIELDS:
            errors[field] = "unknown_field"

    for field in ALLOWED_FIELDS.intersection(data):
        value = data[field]

        if field in ("starts_at", "ends_at"):
            try:
                cleaned[field] = parse_datetime(value)
            except ValueError as exc:
                errors[field] = str(exc)
            continue

        if field in ("client_id", "estimated_guests"):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or (field == "client_id" and value <= 0)
                or (field == "estimated_guests" and value < 0)
            ):
                errors[field] = "invalid_number"
            else:
                cleaned[field] = value
            continue

        if value is not None and not isinstance(value, str):
            errors[field] = "must_be_string"
            continue

        if isinstance(value, str):
            value = value.strip()

        if field in MAX_LENGTHS and value is not None:
            if len(value) > MAX_LENGTHS[field]:
                errors[field] = "too_long"
                continue

        cleaned[field] = value

    if not partial:
        for field in (
            "client_id", "name", "event_type",
            "starts_at", "ends_at"
        ):
            if not cleaned.get(field):
                errors[field] = "required"

    for field in ("name", "event_type"):
        if field in cleaned and not cleaned[field]:
            errors[field] = "required"

    if (
        "starts_at" in cleaned
        and "ends_at" in cleaned
        and cleaned["ends_at"] <= cleaned["starts_at"]
    ):
        errors["ends_at"] = "must_be_after_start"

    return cleaned, errors
