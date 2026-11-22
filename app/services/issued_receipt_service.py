"""Issue once, preserve exact bytes; no changes to payment or audit tables."""
import hashlib
from datetime import timezone
from io import BytesIO
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape
from decimal import Decimal

from flask import current_app
from sqlalchemy.exc import IntegrityError
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.utils import ImageReader

from app.extensions import db
from app.models.company_receipt import CompanyReceiptSettings, IssuedPaymentReceipt
from app.services.payment_receipt_service import load_receipt_data, receipt_number


def local_date(value, tz):
    if value is None:
        return '—'
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo(tz)).strftime('%d/%m/%Y %H:%M')


def render_pdf(contract, payment, tenant, client, settings):
    tz = settings.timezone if settings else tenant.timezone
    try:
        ZoneInfo(tz)
    except (KeyError, ValueError):
        tz = 'UTC'
    name = (settings.commercial_name if settings and settings.commercial_name else tenant.name)
    client_name = client.business_name if client.client_type != 'individual' and client.business_name else ' '.join(filter(None, (client.first_name, client.last_name)))
    stream = BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=(210*mm,297*mm), leftMargin=19*mm, rightMargin=19*mm, topMargin=17*mm, bottomMargin=18*mm, title=f'Comprobante {receipt_number(payment.id)}')
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='ReceiptHeading35', parent=styles['Heading1'], fontSize=18, leading=23, textColor=colors.HexColor('#142c53')))
    styles.add(ParagraphStyle(name='ReceiptSmall35', parent=styles['Normal'], fontSize=9, leading=14, textColor=colors.HexColor('#50617b')))
    styles.add(ParagraphStyle(name='ReceiptAmount35', parent=styles['Normal'], fontSize=23, leading=30, alignment=TA_CENTER, textColor=colors.HexColor('#1857d6')))
    p = lambda x, st='Normal': Paragraph(escape(str(x if x is not None else '—')), styles[st])
    story = []
    if settings and settings.logo_bytes:
        try:
            from PIL import Image as PILImage
            logo = PILImage.open(BytesIO(settings.logo_bytes))
            logo.verify()
            logo = PILImage.open(BytesIO(settings.logo_bytes))
            w,h = logo.size
            scale = min(38*mm/w, 18*mm/h)
            story.append(Image(BytesIO(settings.logo_bytes), width=w*scale, height=h*scale))
            story.append(Spacer(1,4*mm))
        except Exception:
            current_app.logger.warning('Logo almacenado no pudo renderizarse')
    story.extend([p(name, 'ReceiptSmall35'), Spacer(1,4*mm), p('COMPROBANTE DE PAGO','ReceiptHeading35'), p(f'Folio: {receipt_number(payment.id)}', 'ReceiptSmall35'), p('Estado: CONFIRMADO','ReceiptSmall35'), Spacer(1,7*mm)])
    contact = ' | '.join(filter(None, [settings.phone, settings.contact_email, settings.tax_id])) if settings else ''
    address = settings.address if settings else None
    if contact: story.append(p(contact,'ReceiptSmall35'))
    if address: story.append(p(address,'ReceiptSmall35'))
    story.append(Spacer(1,7*mm))
    rows = [[p('Empresa emisora','ReceiptSmall35'),p('Cliente','ReceiptSmall35')],[p(name),p(client_name)],[p('Contrato','ReceiptSmall35'),p('Fecha de confirmación','ReceiptSmall35')],[p(contract.contract_number),p(local_date(payment.confirmed_at,tz)+' ('+tz+')')]]
    table = Table(rows,colWidths=[86*mm,86*mm]);table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),8)]));story.extend([table,Spacer(1,10*mm)])
    story.extend([p('IMPORTE RECIBIDO','ReceiptSmall35'),Spacer(1,2*mm),p(f'{payment.currency or contract.currency} ${Decimal(payment.amount):,.2f}','ReceiptAmount35'),Spacer(1,9*mm)])
    methods = {'cash':'Efectivo','bank_transfer':'Transferencia bancaria','card':'Tarjeta','other':'Otro'}
    types = {'advance':'Anticipo','installment':'Abono'}
    details = [('Tipo de pago',types.get(payment.payment_type,payment.payment_type)),('Método de pago',methods.get(payment.payment_method,payment.payment_method)),('Referencia',payment.reference or '—'),('Pago registrado',local_date(payment.created_at,tz)+' ('+tz+')'),('Identificador del pago',f'#{payment.id}')]
    tab=Table([[p(k,'ReceiptSmall35'),p(v)] for k,v in details],colWidths=[54*mm,118*mm]);tab.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),0.35,colors.HexColor('#d9e1ef')),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]));story.extend([tab,Spacer(1,13*mm),p('Recibo comercial de pago. No es un CFDI ni sustituye una factura fiscal.','ReceiptSmall35')])
    doc.build(story)
    return stream.getvalue()


def get_or_issue(tenant_id, contract_id, payment_id):
    # Validate confirmed payment and tenant membership before reading stored receipt.
    contract,payment,tenant,client = load_receipt_data(tenant_id,contract_id,payment_id)
    existing = db.session.query(IssuedPaymentReceipt).filter_by(tenant_id=tenant_id,contract_id=contract_id,payment_id=payment_id).one_or_none()
    if existing: return existing
    settings = db.session.get(CompanyReceiptSettings,tenant_id)
    pdf = render_pdf(contract,payment,tenant,client,settings)
    if len(pdf) > 10*1024*1024:
        raise ValueError('receipt_pdf_too_large')
    receipt = IssuedPaymentReceipt(tenant_id=tenant_id,contract_id=contract_id,payment_id=payment_id,folio=receipt_number(payment_id),sha256=hashlib.sha256(pdf).hexdigest(),pdf_bytes=pdf)
    try:
        # SAVEPOINT allows a concurrent winner to commit without poisoning session.
        with db.session.begin_nested():
            db.session.add(receipt)
            db.session.flush()
        db.session.commit()
        return receipt
    except IntegrityError:
        db.session.rollback()
        existing=db.session.query(IssuedPaymentReceipt).filter_by(tenant_id=tenant_id,contract_id=contract_id,payment_id=payment_id).one_or_none()
        if existing: return existing
        raise
