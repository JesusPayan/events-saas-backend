
from flask import Blueprint, jsonify, g

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


@bp.post("/contracts/<int:contract_id>/documents/freeze")
@tenant_permission("contracts.update")
def freeze_document(contract_id):
    contract = db.session.get(Contract, contract_id)

    if (
        contract is None
        or contract.tenant_id != g.tenant_id
    ):
        return jsonify(error="contract_not_found"), 404

    tenant = db.session.get(Tenant, g.tenant_id)

    client = db.session.get(Client, contract.client_id)
    event = db.session.get(Event, contract.event_id)

    if (
        tenant is None
        or client is None
        or event is None
        or client.tenant_id != g.tenant_id
        or event.tenant_id != g.tenant_id
    ):
        return jsonify(
            error="contract_relations_invalid"
        ), 409

    try:
        document = freeze_contract_document(
            tenant_id=g.tenant_id,
            contract_id=contract_id,
            tenant=tenant,
            client=client,
            event=event,
            user_id=g.user.id,
        )

        return jsonify(
            id=document.id,
            contract_id=document.contract_id,
            version=document.version,
            sha256=document.sha256,
            byte_size=document.byte_size,
            is_final=document.is_final,
            message="Documento final generado correctamente.",
        ), 201

    except ContractDocumentError as exc:
        return jsonify(
            error=exc.code,
            message=exc.message,
        ), exc.status_code
