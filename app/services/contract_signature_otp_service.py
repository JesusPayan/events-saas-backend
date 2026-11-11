
import hashlib
import hmac
import secrets

from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import select, func

from app.extensions import db
from app.models.contract_signature_request import (
    ContractSignatureRequest,
)
from app.models.contract_signature_otp import (
    ContractSignatureOtp,
)
from app.services.email_service import send_signature_otp

OTP_MINUTES = 5
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_SECONDS = 60
OTP_MAX_ISSUES_PER_HOUR = 3


class SignatureOtpError(Exception):
    def __init__(self, code, message, status_code=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def otp_secret():
    secret = current_app.config.get("SIGNATURE_OTP_SECRET")

    if not secret or len(secret) < 32:
        raise RuntimeError(
            "SIGNATURE_OTP_SECRET debe tener al menos "
            "32 caracteres aleatorios."
        )

    return secret.encode("utf-8")


def hash_otp(request_id, code):
    payload = f"{request_id}:{code}".encode("utf-8")

    return hmac.new(
        otp_secret(),
        payload,
        hashlib.sha256,
    ).hexdigest()


def get_invitation_for_update(token):
    if not isinstance(token, str) or not token:
        raise SignatureOtpError(
            "invalid_invitation",
            "Invitación inválida.",
            404,
        )

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    invitation = db.session.scalar(
        select(ContractSignatureRequest)
        .where(
            ContractSignatureRequest.token_hash == token_hash
        )
        .with_for_update()
    )

    if invitation is None:
        raise SignatureOtpError(
            "invalid_invitation",
            "Invitación inválida.",
            404,
        )

    if invitation.status != "pending":
        raise SignatureOtpError(
            "invalid_invitation_status",
            "La invitación no admite verificación OTP.",
            409,
        )

    if (
        invitation.revoked_at is not None
        or invitation.expires_at <= utc_now()
    ):
        raise SignatureOtpError(
            "invitation_expired",
            "La invitación expiró o fue revocada.",
            410,
        )

    return invitation


def issue_signature_otp(token, send_code):
    """
    send_code(email, code) debe entregar el código
    por un canal privado. No devolver el OTP por HTTP.

    El callback debe ser un adaptador de correo real.
    """
    try:
        invitation = get_invitation_for_update(token)
        now = utc_now()

        last_otp = db.session.scalar(
            select(ContractSignatureOtp)
            .where(
                ContractSignatureOtp.tenant_id
                    == invitation.tenant_id,
                ContractSignatureOtp.request_id
                    == invitation.id,
            )
            .order_by(
                ContractSignatureOtp.created_at.desc(),
                ContractSignatureOtp.id.desc(),
            )
            .limit(1)
        )

        if last_otp is not None:
            elapsed = (
                now - last_otp.created_at
            ).total_seconds()

            if elapsed < OTP_RESEND_SECONDS:
                raise SignatureOtpError(
                    "otp_cooldown",
                    "Espera antes de solicitar otro código.",
                    429,
                )

        issued_last_hour = db.session.scalar(
            select(func.count(ContractSignatureOtp.id))
            .where(
                ContractSignatureOtp.tenant_id
                    == invitation.tenant_id,
                ContractSignatureOtp.request_id
                    == invitation.id,
                ContractSignatureOtp.created_at
                    >= now - timedelta(hours=1),
            )
        ) or 0

        if issued_last_hour >= OTP_MAX_ISSUES_PER_HOUR:
            raise SignatureOtpError(
                "otp_rate_limit",
                "Se alcanzó el límite de códigos.",
                429,
            )

        # Invalidar códigos anteriores.
        previous_codes = db.session.scalars(
            select(ContractSignatureOtp)
            .where(
                ContractSignatureOtp.tenant_id
                    == invitation.tenant_id,
                ContractSignatureOtp.request_id
                    == invitation.id,
                ContractSignatureOtp.consumed_at.is_(None),
            )
            .with_for_update()
        ).all()

        for previous in previous_codes:
            previous.consumed_at = now

        code = f"{secrets.randbelow(1000000):06d}"

        otp = ContractSignatureOtp(
            tenant_id=invitation.tenant_id,
            request_id=invitation.id,
            code_hash=hash_otp(invitation.id, code),
            attempts=0,
            max_attempts=OTP_MAX_ATTEMPTS,
            expires_at=now + timedelta(
                minutes=OTP_MINUTES
            ),
            created_at=now,
        )

        db.session.add(otp)
        db.session.commit()

        # Nunca registrar ni devolver el código
        # en logs o respuestas HTTP.
        send_code(invitation.signer_email, code)

        return {
            "message": "Código enviado.",
            "expires_in_seconds": OTP_MINUTES * 60,
        }

    except SignatureOtpError:
        db.session.rollback()
        raise

    except Exception:
        db.session.rollback()
        raise


def verify_signature_otp(token, code):
    if (
        not isinstance(code, str)
        or len(code) != 6
        or not code.isascii()
        or not code.isdecimal()
    ):
        raise SignatureOtpError(
            "invalid_otp",
            "Código inválido.",
        )

    try:
        invitation = get_invitation_for_update(token)
        now = utc_now()

        otp = db.session.scalar(
            select(ContractSignatureOtp)
            .where(
                ContractSignatureOtp.tenant_id
                    == invitation.tenant_id,
                ContractSignatureOtp.request_id
                    == invitation.id,
                ContractSignatureOtp.consumed_at.is_(None),
            )
            .order_by(
                ContractSignatureOtp.created_at.desc(),
                ContractSignatureOtp.id.desc(),
            )
            .limit(1)
            .with_for_update()
        )

        if otp is None:
            raise SignatureOtpError(
                "otp_not_found",
                "Solicita un nuevo código.",
                400,
            )

        if otp.expires_at <= now:
            otp.consumed_at = now
            db.session.commit()
            raise SignatureOtpError(
                "otp_expired",
                "El código ha expirado.",
                410,
            )

        if otp.attempts >= otp.max_attempts:
            otp.consumed_at = now
            db.session.commit()
            raise SignatureOtpError(
                "otp_locked",
                "Se agotaron los intentos.",
                429,
            )

        expected = hash_otp(invitation.id, code)

        if not hmac.compare_digest(
            otp.code_hash,
            expected,
        ):
            otp.attempts += 1

            if otp.attempts >= otp.max_attempts:
                otp.consumed_at = now

            db.session.commit()

            raise SignatureOtpError(
                "invalid_otp",
                "Código incorrecto.",
                400,
            )

        otp.consumed_at = now
        invitation.verified_at = now
        invitation.status = "verified"

        db.session.commit()

        return {
            "verified": True,
            "request_id": invitation.id,
            "status": invitation.status,
        }

    except SignatureOtpError:
        db.session.rollback()
        raise

    except Exception:
        db.session.rollback()
        raise
