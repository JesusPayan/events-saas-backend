"""Read-only, deterministic commercial payment receipts (not CFDI)."""
from app.branding import BRAND_NAME
from io import BytesIO
from decimal import Decimal
from xml.sax.saxutils import escape
from datetime import timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

from app.extensions import db
from app.models.contract_payment import ContractPayment
from app.models.contract import Contract
from app.models.tenant import Tenant
from app.models.crm import Client


class ReceiptNotFound(Exception):
    pass


def load_receipt_data(tenant_id: int, contract_id: int, payment_id: int):
    """All queries are tenant-scoped; never mutate payment or audit records."""
    contract = db.session.query(Contract).filter_by(id=contract_id, tenant_id=tenant_id).one_or_none()
    if contract is None:
        raise ReceiptNotFound()
    payment = db.session.query(ContractPayment).filter_by(
        id=payment_id, contract_id=contract_id, tenant_id=tenant_id,
        status='confirmed',
    ).one_or_none()
    if payment is None:
        raise ReceiptNotFound()
    tenant = db.session.query(Tenant).filter_by(id=tenant_id).one_or_none()
    client = db.session.query(Client).filter_by(id=contract.client_id, tenant_id=tenant_id).one_or_none()
    if tenant is None or client is None:
        raise ReceiptNotFound()
    return contract, payment, tenant, client


def receipt_number(payment_id: int) -> str:
    # Global payment PK makes the folio unique, immutable and idempotent.
    return f'REC-{payment_id:010d}'


def _safe(value):
    return escape(str(value if value is not None else '—'))


def _date(value):
    if not value:
        return '—'
    # DB timestamps are UTC-naive in the current application.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')


def generate_receipt_pdf(contract, payment, tenant, client) -> bytes:
    """Generate the same content for repeated requests; no DB writes or file storage."""
    stream = BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=(210 * mm, 297 * mm),
                            rightMargin=19 * mm, leftMargin=19 * mm,
                            topMargin=19 * mm, bottomMargin=19 * mm,
                            title=f'Comprobante {receipt_number(payment.id)}',
                            author=BRAND_NAME)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='ReceiptTitle', parent=styles['Heading1'],
                              fontName='Helvetica-Bold', fontSize=18, leading=22,
                              textColor=colors.HexColor('#172b4d'), spaceAfter=8))
    styles.add(ParagraphStyle(name='ReceiptMuted', parent=styles['Normal'],
                              fontSize=9, leading=14, textColor=colors.HexColor('#53657d')))
    styles.add(ParagraphStyle(name='ReceiptValue', parent=styles['Normal'],
                              fontSize=10, leading=15))
    styles.add(ParagraphStyle(name='ReceiptAmount', parent=styles['Normal'],
                              fontName='Helvetica-Bold', fontSize=22, leading=29,
                              alignment=TA_CENTER, textColor=colors.HexColor('#1356d8')))
    styles.add(ParagraphStyle(name='ReceiptFoot', parent=styles['Normal'],
                              fontSize=8, leading=12, alignment=TA_CENTER,
                              textColor=colors.HexColor('#53657d')))
    p = lambda s, style='ReceiptValue': Paragraph(_safe(s), styles[style])
    name = client.business_name if client.client_type != 'individual' and client.business_name else ' '.join(
        filter(None, [client.first_name, client.last_name]))
    currency = payment.currency or contract.currency or 'MXN'
    amount = f'{currency} ${Decimal(payment.amount):,.2f}'
    story = [p(tenant.name, 'ReceiptMuted'), Spacer(1, 5 * mm),
             p('COMPROBANTE DE PAGO', 'ReceiptTitle'),
             p(f'Folio: {receipt_number(payment.id)}', 'ReceiptMuted'),
             p('Estado: CONFIRMADO', 'ReceiptMuted'), Spacer(1, 9 * mm)]
    rows = [
        [p('Empresa emisora', 'ReceiptMuted'), p('Cliente', 'ReceiptMuted')],
        [p(tenant.name), p(name)],
        [p('Contrato', 'ReceiptMuted'), p('Fecha de confirmación', 'ReceiptMuted')],
        [p(contract.contract_number), p(_date(payment.confirmed_at))],
    ]
    details = Table(rows, colWidths=[86 * mm, 86 * mm], hAlign='LEFT')
    details.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                 ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
    story.extend([details, Spacer(1, 9 * mm), p('IMPORTE RECIBIDO', 'ReceiptFoot'),
                  Spacer(1, 3 * mm), p(amount, 'ReceiptAmount'), Spacer(1, 10 * mm)])
    methods = {'cash': 'Efectivo', 'bank_transfer': 'Transferencia bancaria',
               'card': 'Tarjeta', 'other': 'Otro'}
    types = {'advance': 'Anticipo', 'installment': 'Abono'}
    rows = [
        [p('Tipo de pago', 'ReceiptMuted'), p(types.get(payment.payment_type, payment.payment_type))],
        [p('Método de pago', 'ReceiptMuted'), p(methods.get(payment.payment_method, payment.payment_method))],
        [p('Referencia', 'ReceiptMuted'), p(payment.reference or '—')],
        [p('Pago registrado', 'ReceiptMuted'), p(_date(payment.created_at))],
        [p('Identificador del pago', 'ReceiptMuted'), p(f'#{payment.id}')],
    ]
    table = Table(rows, colWidths=[54 * mm, 118 * mm], hAlign='LEFT')
    table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                               ('LINEBELOW', (0, 0), (-1, -1), .3, colors.HexColor('#dbe4f0')),
                               ('TOPPADDING', (0, 0), (-1, -1), 9),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 9)]))
    story.extend([table, Spacer(1, 14 * mm),
                  p('Recibo comercial de pago. Este documento no es un CFDI ni sustituye una factura fiscal.', 'ReceiptFoot'),
                  Spacer(1, 3 * mm), p(f'Emitido con {BRAND_NAME} con base en un pago confirmado.', 'ReceiptFoot')])
    doc.build(story)
    return stream.getvalue()
