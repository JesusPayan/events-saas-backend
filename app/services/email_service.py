"""Reusable SMTP email delivery for Eventos SaaS."""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    pass


def send_email(*, to_email: str, subject: str, text_body: str) -> None:
    host = os.environ.get("SMTP_HOST", "").strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM_EMAIL", "").strip()
    sender_name = os.environ.get("SMTP_FROM_NAME", "Eventos SaaS")
    mode = os.environ.get("SMTP_SECURITY", "starttls").strip().lower()

    if not all((host, username, password, sender)):
        raise EmailDeliveryError("SMTP no está configurado completamente")
    if mode not in ("starttls", "ssl"):
        raise EmailDeliveryError("SMTP_SECURITY debe ser starttls o ssl")
    if not 1 <= port <= 65535:
        raise EmailDeliveryError("SMTP_PORT fuera de rango")

    msg = EmailMessage()
    msg["From"] = formataddr((sender_name, sender))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text_body)

    context = ssl.create_default_context()
    try:
        if mode == "ssl":
            with smtplib.SMTP_SSL(host, port, timeout=15, context=context) as smtp:
                smtp.login(username, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                smtp.login(username, password)
                smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        logger.exception("Error de entrega SMTP")
        raise EmailDeliveryError("No se pudo entregar el correo") from exc


def send_signature_otp(to_email: str, code: str) -> None:
    send_email(
        to_email=to_email,
        subject="Código de verificación para firmar tu contrato",
        text_body=(
            "Recibimos una solicitud para firmar un contrato en Eventos SaaS.\n\n"
            f"Tu código de verificación es: {code}\n\n"
            "Este código vence en 5 minutos. No lo compartas.\n"
            "Si no solicitaste esta verificación, ignora este mensaje."
        ),
    )
