
import re

ALLOWED_FIELDS = {
    "client_type", "first_name", "last_name",
    "business_name", "email", "phone", "whatsapp",
    "address", "city", "state", "postal_code", "notes"
}

MAX_LENGTHS = {
    "first_name": 100,
    "last_name": 150,
    "business_name": 180,
    "email": 180,
    "phone": 30,
    "whatsapp": 30,
    "address": 255,
    "city": 100,
    "state": 100,
    "postal_code": 15
}


def validate_client(data, partial=False):
    if not isinstance(data, dict):
        return {}, {"body": "invalid_json"}

    errors = {}
    cleaned = {}

    for field in data:
        if field not in ALLOWED_FIELDS:
            errors[field] = "unknown_field"

    for field in ALLOWED_FIELDS.intersection(data):
        value = data[field]

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
        cleaned.setdefault("client_type", "individual")

    client_type = cleaned.get("client_type")

    if client_type is not None and client_type not in (
        "individual", "business"
    ):
        errors["client_type"] = "invalid_type"

    if not partial and not cleaned.get("first_name"):
        errors["first_name"] = "required"

    if "first_name" in cleaned and not cleaned["first_name"]:
        errors["first_name"] = "required"

    if cleaned.get("email"):
        email = cleaned["email"].lower()

        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            errors["email"] = "invalid_email"

        cleaned["email"] = email
    if not partial and cleaned.get("client_type") == "business":
        if not cleaned.get("business_name"):
            errors["business_name"] = "required"

    return cleaned, errors
