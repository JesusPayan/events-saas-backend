
from flask import Blueprint, request, jsonify, g
from sqlalchemy.exc import IntegrityError, DataError

from app.extensions import db
from app.security import tenant_permission
from flask import send_file
from sqlalchemy import select

from app.models.tenant import Tenant
from app.models.crm import Client
from app.models.event import Event
from app.services.contract_pdf_service import generate_contract_pdf
from app.services.contract_service import (
    ContractError,
    create_contract_from_quote,
    get_contract,
    list_contracts,
    change_contract_status,
    get_contract_history,
    serialize_contract,
    serialize_contract_history,
)
from io import BytesIO

from app.models.contract_document import ContractDocument
from app.services.contract_document_service import (
    ContractDocumentError,
    read_verified_document,
)


bp = Blueprint("contracts", __name__)


def contract_error_response(exc):
    return jsonify(
        error=exc.code,
        message=exc.message,
    ), exc.status_code


@bp.post("/contracts")
@tenant_permission("contracts.create")
def create_contract_endpoint():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(error="invalid_json"), 400

    if set(data) != {"quote_id"}:
        return jsonify(
            error="invalid_fields",
            message="Solo se permite quote_id.",
        ), 400

    quote_id = data.get("quote_id")

    if (
        isinstance(quote_id, bool)
        or not isinstance(quote_id, int)
        or quote_id <= 0
    ):
        return jsonify(
            error="invalid_quote_id",
        ), 400

    try:
        contract = create_contract_from_quote(
            tenant_id=g.tenant_id,
            quote_id=quote_id,
            user_id=g.user.id,
        )

        return jsonify(
            serialize_contract(contract, include_items=True)
        ), 201

    except ContractError as exc:
        db.session.rollback()
        return contract_error_response(exc)

    except (IntegrityError, DataError):
        db.session.rollback()
        return jsonify(
            error="contract_conflict_or_invalid_reference"
        ), 409


@bp.get("/contracts")
@tenant_permission("contracts.read")
def list_contracts_endpoint():
    page = max(
        1,
        request.args.get("page", 1, type=int),
    )

    per_page = min(
        100,
        max(
            1,
            request.args.get("per_page", 20, type=int),
        ),
    )

    result = list_contracts(
        tenant_id=g.tenant_id,
        page=page,
        per_page=per_page,
    )

    return jsonify({
        "items": [
            serialize_contract(contract)
            for contract in result.items
        ],
        "total": result.total,
        "page": result.page,
        "per_page": result.per_page,
        "pages": result.pages,
    }), 200


@bp.get("/contracts/<int:contract_id>")
@tenant_permission("contracts.read")
def get_contract_endpoint(contract_id):
    contract = get_contract(
        tenant_id=g.tenant_id,
        contract_id=contract_id,
    )

    if contract is None:
        return jsonify(error="not_found"), 404

    return jsonify(
        serialize_contract(contract, include_items=True)
    ), 200


@bp.patch("/contracts/<int:contract_id>/status")
@tenant_permission("contracts.update")
def change_contract_status_endpoint(contract_id):
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(error="invalid_json"), 400

    if set(data) - {"status", "notes"}:
        return jsonify(error="unknown_fields"), 400

    status = data.get("status")
    notes = data.get("notes")

    if not isinstance(status, str):
        return jsonify(error="invalid_status"), 400

    if notes is not None and (
        not isinstance(notes, str)
        or len(notes) > 2000
    ):
        return jsonify(error="invalid_notes"), 400

    try:
        contract = change_contract_status(
            tenant_id=g.tenant_id,
            contract_id=contract_id,
            new_status=status,
            user_id=g.user.id,
            notes=notes.strip() if notes else None,
        )

        return jsonify(
            serialize_contract(contract, include_items=True)
        ), 200

    except ContractError as exc:
        db.session.rollback()
        return contract_error_response(exc)

    except (IntegrityError, DataError):
        db.session.rollback()
        return jsonify(
            error="contract_conflict_or_invalid_reference"
        ), 409


@bp.get("/contracts/<int:contract_id>/history")
@tenant_permission("contracts.read")
def get_contract_history_endpoint(contract_id):
    try:
        history = get_contract_history(
            tenant_id=g.tenant_id,
            contract_id=contract_id,
        )

        return jsonify({
            "items": [
                serialize_contract_history(item)
                for item in history
            ],
            "total": len(history),
        }), 200

    except ContractError as exc:
        return contract_error_response(exc)
    
    

@bp.get("/contracts/<int:contract_id>/pdf")
@tenant_permission("contracts.read")
def download_contract_pdf(contract_id):
    tenant_id = g.tenant_id

    contract = get_contract(
        tenant_id=tenant_id,
        contract_id=contract_id,
    )

    if contract is None:
        return jsonify(error="not_found"), 404

    # Buscar la versión final más reciente.
    document = db.session.scalar(
        select(ContractDocument)
        .where(
            ContractDocument.tenant_id == tenant_id,
            ContractDocument.contract_id == contract_id,
            ContractDocument.is_final.is_(True),
        )
        .order_by(
            ContractDocument.version.desc(),
            ContractDocument.id.desc(),
        )
        .limit(1)
    )

    # Si existe un documento final, entregar exactamente
    # los bytes originales después de validar su integridad.
    if document is not None:
        try:
            pdf_bytes = read_verified_document(document)

        except ContractDocumentError as exc:
            return jsonify(
                error=exc.code,
                message=exc.message,
            ), exc.status_code

        response = send_file(
            BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=(
                f"contrato-{contract.id}"
                f"-version-{document.version}.pdf"
            ),
        )
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    # No regenerar un contrato activo o firmado.
    # Su documento original es obligatorio.
    if contract.status != "draft":
        return jsonify(
            error="final_document_not_found",
            message=(
                "El contrato no tiene un documento final "
                "disponible para descargar."
            ),
        ), 409

    # Si existe una firma, no permitir reconstruir
    # el contrato a partir de datos actuales.
    from app.services.contract_protection_service import (
        has_registered_signatures,
    )

    if has_registered_signatures(
        tenant_id=tenant_id,
        contract_id=contract_id,
    ):
        return jsonify(
            error="signed_document_not_found",
            message=(
                "Existe una firma registrada, pero no se "
                "encontró el documento final."
            ),
        ), 409

    # Solo para borradores sin documento final:
    # generar una vista preliminar.
    tenant = db.session.scalar(
        select(Tenant).where(
            Tenant.id == tenant_id,
        )
    )

    client = db.session.scalar(
        select(Client).where(
            Client.id == contract.client_id,
            Client.tenant_id == tenant_id,
        )
    )

    event = db.session.scalar(
        select(Event).where(
            Event.id == contract.event_id,
            Event.client_id == contract.client_id,
            Event.tenant_id == tenant_id,
        )
    )

    if tenant is None or client is None or event is None:
        return jsonify(
            error="related_data_not_found"
        ), 404

    pdf = generate_contract_pdf(
        contract=contract,
        tenant=tenant,
        client=client,
        event=event,
    )

    response = send_file(
        pdf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"contrato-{contract.id}-borrador.pdf",
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

