"""Envío Gmail SMTP de comprobante adjunto, posterior al commit de firma."""
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.services.contract_signature_receipt_service import get_receipt_data, generate_signature_receipt


def send_signature_receipt(*, tenant_id, request_id):
    invitation, signature, document, audit, _ = get_receipt_data(
        tenant_id=tenant_id, request_id=request_id,
    )
    pdf = generate_signature_receipt(tenant_id=tenant_id, request_id=request_id)
    host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    port = int(os.environ.get('SMTP_PORT', '587'))
    security = os.environ.get('SMTP_SECURITY', 'starttls').strip().lower()
    username = os.environ.get('SMTP_USERNAME', '').strip()
    password = os.environ.get('SMTP_PASSWORD', '').replace(' ', '')
    sender = os.environ.get('SMTP_FROM_EMAIL', username).strip()
    sender_name = os.environ.get('SMTP_FROM_NAME', 'Eventos SaaS')
    if not username or not password or not sender:
        raise RuntimeError('Credenciales SMTP no configuradas')
    msg = EmailMessage()
    msg['From'] = formataddr((sender_name, sender))
    msg['To'] = invitation.signer_email
    msg['Subject'] = f'Comprobante de firma - Contrato #{invitation.contract_id}'
    msg.set_content(
        f'Hola {signature.signer_name},\n\n'
        f'Tu firma del contrato #{invitation.contract_id} quedó registrada. '
        'Adjuntamos el comprobante PDF de evidencia.\n\n'
        'Conserva este correo y el comprobante.\n\nEventos SaaS'
    )
    msg.add_attachment(pdf, maintype='application', subtype='pdf',
                       filename=f'comprobante-firma-contrato-{invitation.contract_id}-solicitud-{request_id}.pdf')
    context = ssl.create_default_context()
    if security == 'ssl':
        with smtplib.SMTP_SSL(host, port, timeout=30, context=context) as smtp:
            smtp.login(username, password)
            smtp.send_message(msg)
    elif security == 'starttls':
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(username, password)
            smtp.send_message(msg)
    else:
        raise RuntimeError('SMTP_SECURITY debe ser ssl o starttls')
    return True
