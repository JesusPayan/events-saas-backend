
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.contract import Contract
from app.models.contract_document import ContractDocument
from app.models.contract_signature_request import ContractSignatureRequest
import re

class SignatureRequestError(Exception):
    def __init__(self, code, message, status_code=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_signature_request(
    tenant_id,
    contract_id,
    document_id,
    signer_role,
    signer_name,
    signer_email,
    user_id,
    expires_hours=72,
):
    if signer_role not in ("client", "provider"):
        raise SignatureRequestError(
            "invalid_signer_role",
            "El rol del firmante no es válido.",
        )

    if not isinstance(signer_name, str) or not signer_name.strip():
        raise SignatureRequestError(
            "invalid_signer_name",
            "El nombre del firmante es obligatorio.",
        )

    if (
        not isinstance(signer_email, str)
        or not signer_email.strip()
        or len(signer_email) > 254
    ):
        raise SignatureRequestError(
            "invalid_signer_email",
            "El correo del firmante no es válido.",
        )

    if (
        isinstance(expires_hours, bool)
        or not isinstance(expires_hours, int)
        or not 1 <= expires_hours <= 168
    ):
        raise SignatureRequestError(
            "invalid_expiration",
            "La vigencia debe estar entre 1 y 168 horas.",
        )

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
            raise SignatureRequestError(
                "contract_not_found",
                "El contrato no existe.",
                404,
            )

        if contract.status in ("cancelled", "completed"):
            raise SignatureRequestError(
                "contract_not_signable",
                "El contrato no admite nuevas firmas.",
                409,
            )

        document = db.session.scalar(
            select(ContractDocument).where(
                ContractDocument.id == document_id,
                ContractDocument.tenant_id == tenant_id,
                ContractDocument.contract_id == contract_id,
            )
        )

        if document is None:
            raise SignatureRequestError(
        "document_not_found",
        "No existe una versión documental válida.",
        404,
    )

# Solo se permiten documentos finales
        if not document.is_final:
            raise SignatureRequestError(
        "document_not_final",
        "El documento debe estar finalizado antes de firmarse.",
        409,
    )

# Verificar metadatos de integridad
        if (
            document.mime_type != "application/pdf"
            or not re.fullmatch(r"[0-9a-fA-F]{64}", document.sha256 or "")
            or document.byte_size <= 0
        ):
            raise SignatureRequestError(
        "invalid_document",
        "Los metadatos del documento no son válidos.",
        409,
    )
        # TODO: comprobar que la versión documental esté
        # congelada y que su hash corresponda al PDF
        # almacenado, antes de habilitar la firma.

        token = secrets.token_urlsafe(32)

        invitation = ContractSignatureRequest(
            tenant_id=tenant_id,
            contract_id=contract_id,
            document_id=document_id,
            signer_role=signer_role,
            signer_name=signer_name.strip(),
            signer_email=signer_email.strip().lower(),
            token_hash=hash_token(token),
            status="pending",
            expires_at=utc_now() + timedelta(hours=expires_hours),
            created_by=user_id,
        )

        db.session.add(invitation)
        db.session.commit()

        return invitation, token

    except SignatureRequestError:
        db.session.rollback()
        raise

    except IntegrityError as exc:
        db.session.rollback()
        raise SignatureRequestError(
            "signature_request_conflict",
            "No se pudo generar la invitación.",
            409,
        ) from exc

    except Exception:
        db.session.rollback()
        raise
