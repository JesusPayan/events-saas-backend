"""COM-02.1.7: comprobante PDF de firma, sin alterar el contrato original."""
import hashlib
import io
from datetime import timezone
from html import escape
from pathlib import Path

from flask import current_app
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from sqlalchemy import select

from app.extensions import db
from app.models.contract_signature import ContractSignature
from app.models.contract_signature_request import ContractSignatureRequest
from app.models.contract_document import ContractDocument
from app.models.contract_signature_audit import ContractSignatureAudit
from app.services.contract_document_service import read_verified_document


class ReceiptError(Exception):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code = code
        self.status = status


def _signature_bytes(signature):
    root_value = current_app.config.get('CONTRACT_SIGNATURE_STORAGE_ROOT')
    if not root_value:
        raise ReceiptError('signature_storage_not_configured', 500)
    root = Path(root_value).resolve()
    path = (root / signature.signature_storage_key).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise ReceiptError('signature_file_missing')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != signature.signature_sha256:
        raise ReceiptError('signature_integrity_failed')
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ReceiptError('invalid_signature_image')
    return data


def get_receipt_data(*, tenant_id, request_id):
    invitation = db.session.scalar(select(ContractSignatureRequest).where(
        ContractSignatureRequest.tenant_id == tenant_id,
        ContractSignatureRequest.id == request_id,
        ContractSignatureRequest.status == 'signed',
    ))
    if invitation is None:
        raise ReceiptError('signed_invitation_not_found', 404)
    signature = db.session.scalar(select(ContractSignature).where(
        ContractSignature.tenant_id == tenant_id,
        ContractSignature.request_id == request_id,
    ))
    document = db.session.scalar(select(ContractDocument).where(
        ContractDocument.tenant_id == tenant_id,
        ContractDocument.id == invitation.document_id,
        ContractDocument.contract_id == invitation.contract_id,
    ))
    if signature is None or document is None or signature.document_id != document.id:
        raise ReceiptError('receipt_evidence_incomplete')
    read_verified_document(document)
    if signature.document_sha256 != document.sha256:
        raise ReceiptError('document_hash_mismatch')
    audit = db.session.scalar(select(ContractSignatureAudit).where(
        ContractSignatureAudit.tenant_id == tenant_id,
        ContractSignatureAudit.request_id == request_id,
        ContractSignatureAudit.event_type == 'contract_signed',
    ).order_by(ContractSignatureAudit.id.asc()))
    if audit is None:
        raise ReceiptError('signature_audit_missing')
    return invitation, signature, document, audit, _signature_bytes(signature)


def _datetime(value):
    if value is None:
        return 'No registrado'
    # Fechas UTC naive conforme a los modelos actuales.
    return value.strftime('%Y-%m-%d %H:%M:%S UTC')


def generate_signature_receipt(*, tenant_id, request_id):
    invitation, signature, document, audit, signature_bytes = get_receipt_data(
        tenant_id=tenant_id, request_id=request_id,
    )
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20*mm,
                            rightMargin=20*mm, topMargin=19*mm, bottomMargin=18*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='ReceiptTitleX', parent=styles['Title'], fontSize=17,
                              leading=21, textColor=colors.HexColor('#17243B'), spaceAfter=12))
    styles.add(ParagraphStyle(name='ReceiptBodyX', parent=styles['BodyText'], fontSize=9,
                              leading=13, spaceAfter=7, wordWrap='CJK'))
    styles.add(ParagraphStyle(name='ReceiptTinyX', parent=styles['BodyText'], fontSize=7,
                              leading=10, wordWrap='CJK'))
    styles.add(ParagraphStyle(name='ReceiptHeadingX', parent=styles['Heading2'], fontSize=11,
                              textColor=colors.HexColor('#17243B'), spaceBefore=12, spaceAfter=7))
    p = lambda v: Paragraph(escape(str(v or '')), styles['ReceiptBodyX'])
    story = [Paragraph('COMPROBANTE DE FIRMA ELECTRÓNICA', styles['ReceiptTitleX']),
             p('Eventos SaaS · Evidencia técnica de aceptación y firma'),
             Paragraph('Identificación', styles['ReceiptHeadingX'])]
    rows = [
        ('Contrato', f'#{invitation.contract_id}'),
        ('Documento', f'#{document.id} · versión {document.version}'),
        ('Invitación', f'#{invitation.id}'),
        ('Firma', f'#{signature.id}'),
        ('Firmante', signature.signer_name),
        ('Correo verificado', invitation.signer_email),
        ('Rol', invitation.signer_role),
        ('Verificación OTP', _datetime(invitation.verified_at)),
        ('Consentimiento aceptado', _datetime(signature.consent_accepted_at)),
        ('Fecha de firma', _datetime(signature.signed_at)),
        ('Versión de consentimiento', signature.consent_version),
        ('Evento de auditoría', f'#{audit.id} · {audit.event_type}'),
    ]
    table = Table([[p(k), p(v)] for k, v in rows], colWidths=[55*mm, 115*mm], hAlign='LEFT')
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#F4F6FA')]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
    ]))
    story += [table, Paragraph('Firma capturada', styles['ReceiptHeadingX'])]
    img = Image(io.BytesIO(signature_bytes))
    scale = min(105*mm / img.imageWidth, 32*mm / img.imageHeight, 1)
    img.drawWidth, img.drawHeight = img.imageWidth*scale, img.imageHeight*scale
    img.hAlign = 'LEFT'
    story += [img, Spacer(1, 5*mm), Paragraph('Consentimiento registrado', styles['ReceiptHeadingX']),
              p(signature.consent_text), Paragraph('Integridad documental', styles['ReceiptHeadingX'])]
    for label, value in [('SHA-256 del PDF original', document.sha256),
                         ('SHA-256 de la imagen de firma', signature.signature_sha256)]:
        story.append(p(label))
        story.append(Paragraph(escape(value), styles['ReceiptTinyX']))
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph('Este comprobante documenta la evidencia técnica almacenada por el sistema. '
                           'No constituye por sí solo una firma electrónica avanzada ni una certificación de identidad.',
                           styles['ReceiptTinyX']))
    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#566174'))
        canvas.drawString(20*mm, 12*mm, 'Eventos SaaS · Comprobante de firma')
        canvas.drawRightString(190*mm, 12*mm, f'Página {_doc.page}')
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
