
import hashlib
import os
import uuid

from pathlib import Path

from flask import current_app
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.contract import Contract
from app.models.contract_document import ContractDocument
from app.models.contract_signature_request import (
    ContractSignatureRequest,
)

from app.services.contract_pdf_service import (
    generate_contract_pdf,
)


class ContractDocumentError(Exception):
    def __init__(self, code, message, status_code=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def storage_root():
    root = current_app.config.get(
        "CONTRACT_DOCUMENT_STORAGE_ROOT"
    )

    if not root:
        raise RuntimeError(
            "CONTRACT_DOCUMENT_STORAGE_ROOT no configurado"
        )

    return Path(root).resolve()


def document_path(storage_key):
    root = storage_root()

    if not storage_key:
        raise ContractDocumentError(
            "invalid_storage_key",
            "Ubicación del documento inválida.",
            409,
        )

    path = (root / storage_key).resolve()

    if not path.is_relative_to(root):
        raise ContractDocumentError(
            "invalid_storage_key",
            "Ubicación del documento inválida.",
            409,
        )

    return path


def read_verified_document(document):
    path = document_path(document.storage_key)

    if not path.is_file() or path.is_symlink():
        raise ContractDocumentError(
            "document_file_missing",
            "El archivo del documento no está disponible.",
            409,
        )

    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()

    if (
        digest != document.sha256
        or len(data) != document.byte_size
        or not data.startswith(b"%PDF-")
    ):
        raise ContractDocumentError(
            "document_integrity_failed",
            "Falló la verificación de integridad del PDF.",
            409,
        )

    return data


def freeze_contract_document(
    *,
    tenant_id,
    contract_id,
    tenant,
    client,
    event,
    user_id,
):
    created_path = None

    try:
        contract = db.session.scalar(
            select(Contract)
            .where(
                Contract.id == contract_id,
                Contract.tenant_id == tenant_id,
            )
            .with_for_update()
        )

        if contract is None:
            raise ContractDocumentError(
                "contract_not_found",
                "El contrato no existe.",
                404,
            )

        if contract.status in ("cancelled", "completed"):
            raise ContractDocumentError(
                "contract_not_signable",
                "El contrato no admite nuevas firmas.",
                409,
            )

        # Evitar crear otra versión mientras existan
        # invitaciones pendientes o verificadas.
        active_request = db.session.scalar(
            select(ContractSignatureRequest.id)
            .where(
                ContractSignatureRequest.tenant_id
                    == tenant_id,
                ContractSignatureRequest.contract_id
                    == contract_id,
                ContractSignatureRequest.status.in_(
                    ("pending", "verified")
                ),
            )
            .limit(1)
        )

        if active_request is not None:
            raise ContractDocumentError(
                "active_signature_requests",
                "Revoca las invitaciones activas antes "
                "de generar una nueva versión.",
                409,
            )

        # No generar nuevas versiones después de
        # registrar una firma sin un flujo formal
        # de sustitución documental.
        signed_request = db.session.scalar(
            select(ContractSignatureRequest.id)
            .where(
                ContractSignatureRequest.tenant_id
                    == tenant_id,
                ContractSignatureRequest.contract_id
                    == contract_id,
                ContractSignatureRequest.status == "signed",
            )
            .limit(1)
        )

        if signed_request is not None:
            raise ContractDocumentError(
                "contract_already_signed",
                "El contrato ya tiene una firma registrada.",
                409,
            )

        last_version = db.session.scalar(
            select(func.max(ContractDocument.version))
            .where(
                ContractDocument.tenant_id == tenant_id,
                ContractDocument.contract_id == contract_id,
            )
        ) or 0

        version = last_version + 1

        pdf_buffer = generate_contract_pdf(
            contract=contract,
            tenant=tenant,
            client=client,
            event=event,
        )

        pdf_bytes = pdf_buffer.getvalue()

        if not pdf_bytes.startswith(b"%PDF-"):
            raise ContractDocumentError(
                "invalid_pdf",
                "El generador no produjo un PDF válido.",
                500,
            )

        digest = hashlib.sha256(
            pdf_bytes
        ).hexdigest()

        storage_key = (
            f"tenants/{tenant_id}/"
            f"contracts/{contract_id}/"
            f"{uuid.uuid4().hex}.pdf"
        )

        destination = document_path(storage_key)
        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        # Creación exclusiva: nunca sobrescribir.
        with destination.open("xb") as output:
            created_path = destination
            output.write(pdf_bytes)
            output.flush()
            os.fsync(output.fileno())

        document = ContractDocument(
            tenant_id=tenant_id,
            contract_id=contract_id,
            version=version,
            storage_key=storage_key,
            sha256=digest,
            byte_size=len(pdf_bytes),
            mime_type="application/pdf",
            is_final=True,
            created_by=user_id,
        )

        db.session.add(document)
        db.session.commit()

        return document

    except ContractDocumentError:
        db.session.rollback()
        if created_path:
            created_path.unlink(missing_ok=True)
        raise

    except IntegrityError as exc:
        db.session.rollback()
        if created_path:
            created_path.unlink(missing_ok=True)
        raise ContractDocumentError(
            "document_version_conflict",
            "No se pudo registrar la versión documental.",
            409,
        ) from exc

    except Exception:
        db.session.rollback()
        if created_path:
            created_path.unlink(missing_ok=True)
        raise
