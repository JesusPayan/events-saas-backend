
from flask import Blueprint, request, jsonify, g
from sqlalchemy.exc import IntegrityError, DataError
from flask import send_file
from sqlalchemy import select

from app.models.tenant import Tenant
from app.models.crm import Client
from app.models.event import Event
from app.services.quote_pdf_service import generate_quote_pdf
from app.extensions import db
from app.security import tenant_permission
from app.services.quote_service import (
    create_quote,
    get_quote,
    list_quotes,
    serialize_quote,
    change_quote_status 
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

@bp.patch("/quotes/<int:quote_id>/status")
@tenant_permission("quotes.create")
def change_quote_status_endpoint(quote_id):
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(
            error="invalid_json"
        ), 400

    if set(data) - {"status", "notes"}:
        return jsonify(
            error="unknown_fields"
        ), 400

    try:
        quote = change_quote_status(
            tenant_id=g.tenant_id,
            quote_id=quote_id,
            user_id=g.user.id,
            new_status=data.get("status"),
            notes=data.get("notes"),
        )

        db.session.commit()

        return jsonify(
            serialize_quote(quote, include_items=True)
        ), 200

    except QuoteValidationError as exc:
        db.session.rollback()

        return jsonify(
            error="validation_error",
            details=exc.details,
        ), exc.status_code

    except Exception:
        db.session.rollback()
        raise
    from flask import send_file
@bp.get("/quotes/<int:quote_id>/pdf")
@tenant_permission("quotes.read")
def download_quote_pdf(quote_id):
    tenant_id = g.tenant_id

    quote = get_quote(tenant_id, quote_id)

    if quote is None:
        return jsonify(error="not_found"), 404

    tenant = db.session.scalar(
        select(Tenant).where(Tenant.id == tenant_id)
    )

    client = db.session.scalar(
        select(Client).where(
            Client.id == quote.client_id,
            Client.tenant_id == tenant_id,
        )
    )

    event = db.session.scalar(
        select(Event).where(
            Event.id == quote.event_id,
            Event.client_id == quote.client_id,
            Event.tenant_id == tenant_id,
        )
    )

    if tenant is None or client is None or event is None:
        return jsonify(error="related_data_not_found"), 404

    pdf = generate_quote_pdf(
        quote=quote,
        tenant=tenant,
        client=client,
        event=event,
    )

    return send_file(
        pdf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"cotizacion-{quote.id}.pdf",
    )