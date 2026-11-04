
from flask import Blueprint, request, jsonify, g
from sqlalchemy.exc import IntegrityError, DataError

from app.extensions import db
from app.security import tenant_permission
from app.services.quote_service import (
    create_quote,
    get_quote,
    list_quotes,
    serialize_quote,
)
from app.services.quote_validation import QuoteValidationError


bp = Blueprint("quotes", __name__)


@bp.post("/quotes")
@tenant_permission("quotes.create")
def create_quote_endpoint():
    data = request.get_json(silent=True)

    try:
        quote_id = create_quote(
            tenant_id=g.tenant_id,
            user_id=g.user.id,
            data=data
        )

        db.session.commit()

    except QuoteValidationError as exc:
        db.session.rollback()
        return jsonify(
            error="validation_error",
            details=exc.details
        ), exc.status_code

    except (IntegrityError, DataError):
        db.session.rollback()
        return jsonify(
            error="quote_conflict_or_invalid_reference"
        ), 409

    quote = get_quote(g.tenant_id, quote_id)

    return jsonify(
        serialize_quote(quote, include_items=True)
    ), 201


@bp.get("/quotes")
@tenant_permission("quotes.read")
def list_quotes_endpoint():

    page = max(
        1, request.args.get("page", 1, type=int)
    )
    per_page = min(
        100,
        max(1, request.args.get("per_page", 20, type=int))
    )

    result = list_quotes(
        tenant_id=g.tenant_id,
        page=page,
        per_page=per_page
    )
    print(result)   
    return jsonify({
        "items": [
            serialize_quote(quote)
            for quote in result.items
        ],
        "total": result.total,
        "page": result.page,
        "per_page": result.per_page,
        "pages": result.pages
    })


@bp.get("/quotes/<int:quote_id>")
@tenant_permission("quotes.read")
def get_quote_endpoint(quote_id):
    quote = get_quote(g.tenant_id, quote_id)

    if quote is None:
        return jsonify(error="not_found"), 404

    return jsonify(
        serialize_quote(quote, include_items=True)
    )
