
from flask import Blueprint, jsonify, g
from sqlalchemy import select

from app.extensions import db
from app.security import tenant_permission

from app.models.tenant import Tenant
from app.models.crm import Client
from app.models.event import Event
from app.models.contract import Contract

from app.services.contract_document_service import (
    freeze_contract_document,
    ContractDocumentError,
)

bp = Blueprint("contract_documents", __name__)


@bp.post("/contracts/<int:contract_id>/documents/finalize")
@tenant_permission("contracts.update")
def finalize_contract_document_endpoint(contract_id):
    tenant_id = g.tenant_id

    # Obtener contrato de la empresa seleccionada.
    contract = db.session.scalar(
        select(Contract).where(
            Contract.id == contract_id,
            Contract.tenant_id == tenant_id,
        )
    )

    if contract is None:
        return jsonify(
            error="contract_not_found",
            message="El contrato no existe."
        ), 404

    # Obtener empresa.
    tenant = db.session.scalar(
        select(Tenant).where(
            Tenant.id == tenant_id
        )
    )

    # Obtener cliente asociado.
    client = db.session.scalar(
        select(Client).where(
            Client.id == contract.client_id,
            Client.tenant_id == tenant_id,
        )
    )

    # Obtener evento asociado al contrato y cliente.
    event = db.session.scalar(
        select(Event).where(
            Event.id == contract.event_id,
            Event.client_id == contract.client_id,
            Event.tenant_id == tenant_id,
        )
    )

    if tenant is None or client is None or event is None:
        return jsonify(
            error="contract_relations_invalid",
            message=(
                "No se encontraron las relaciones "
                "válidas del contrato."
            )
        ), 409

    try:
        document = freeze_contract_document(
            tenant_id=tenant_id,
            contract_id=contract_id,
            tenant=tenant,
            client=client,
            event=event,
            user_id=g.user.id,
        )

        return jsonify({
            "id": document.id,
            "contract_id": document.contract_id,
            "version": document.version,
            "sha256": document.sha256,
            "byte_size": document.byte_size,
            "mime_type": document.mime_type,
            "is_final": document.is_final,
            "created_at": (
                document.created_at.isoformat()
                if document.created_at else None
            ),
            "message": "Documento final generado correctamente."
        }), 201

    except ContractDocumentError as exc:
        return jsonify(
            error=exc.code,
            message=exc.message,
        ), exc.status_code
