"""COM-02.1: PDF de contrato (presentación documental, no firma electrónica)."""
from io import BytesIO
from decimal import Decimal
from html import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from sqlalchemy import select
from app.extensions import db
from app.models.contract_item import ContractItem

DARK = colors.HexColor('#17243B')
MUTED = colors.HexColor('#566174')
LINE = colors.HexColor('#DCE2EA')


def _value(obj, *fields, default='No especificado'):
    for field in fields:
        val = getattr(obj, field, None)
        if val is not None and str(val).strip():
            return str(val)
    return default


def _p(value):
    return escape(str(value or '')).replace('\n', '<br/>')


def _money(value, currency='MXN'):
    return f"{Decimal(str(value or 0)):,.2f} {currency}"


def generate_contract_pdf(*, contract, tenant, client, event):
    """Devuelve BytesIO listo para flask.send_file. Requiere entidades del mismo tenant."""
    if not (contract.tenant_id == tenant.id == client.tenant_id == event.tenant_id):
        raise ValueError('Las entidades no pertenecen a la misma empresa')
    if contract.client_id != client.id or contract.event_id != event.id:
        raise ValueError('Cliente o evento no corresponde al contrato')

    items = db.session.scalars(
        select(ContractItem)
        .where(ContractItem.tenant_id == contract.tenant_id,
               ContractItem.contract_id == contract.id)
        .order_by(ContractItem.sort_order.asc(), ContractItem.id.asc())
    ).all()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=19*mm,
                            leftMargin=19*mm, topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='ContractTitleX', parent=styles['Title'],
                              fontName='Helvetica-Bold', fontSize=16, leading=20,
                              textColor=DARK, spaceAfter=10))
    styles.add(ParagraphStyle(name='ContractBodyX', parent=styles['BodyText'],
                              fontName='Helvetica', fontSize=9, leading=14, spaceAfter=5))
    styles.add(ParagraphStyle(name='ContractSmallX', parent=styles['BodyText'],
                              fontName='Helvetica', fontSize=8, leading=11))
    styles.add(ParagraphStyle(name='ContractHeadingX', parent=styles['Heading2'],
                              fontSize=10, leading=14, textColor=DARK, spaceBefore=12, spaceAfter=6))
    styles.add(ParagraphStyle(name='ContractRightX', parent=styles['BodyText'],
                              alignment=TA_RIGHT, fontSize=9))
    body = lambda s: Paragraph(_p(s), styles['ContractBodyX'])
    small = lambda s: Paragraph(_p(s), styles['ContractSmallX'])
    story = []
    story.append(Paragraph('CONTRATO DE PRESTACIÓN DE SERVICIOS PARA EVENTO', styles['ContractTitleX']))
    story.append(body(f"Contrato: {_value(contract, 'contract_number')}  |  Estado: {_value(contract, 'status')}"))
    story.append(body(f"Fecha de emisión: {_value(contract, 'created_at')}"))

    story.append(Paragraph('1. Partes contratantes', styles['ContractHeadingX']))
    story.append(body(f"Empresa: {_value(tenant, 'legal_name', 'business_name', 'company_name', 'name')}"))
    story.append(body(f"Cliente: {_value(client, 'business_name', 'company_name', 'full_name', 'name')}"))
    story.append(body(f"Correo del cliente: {_value(client, 'email')}  |  Teléfono: {_value(client, 'phone', 'whatsapp')}"))

    story.append(Paragraph('2. Datos del evento', styles['ContractHeadingX']))
    story.append(body(f"Evento: {_value(event, 'name', 'title', 'event_name')}"))
    story.append(body(f"Inicio: {_value(event, 'starts_at')}  |  Fin: {_value(event, 'ends_at')}"))
    story.append(body(f"Lugar: {_value(event, 'venue', 'location', 'address')}"))

    story.append(Paragraph('3. Conceptos contratados', styles['ContractHeadingX']))
    headers = ['Concepto', 'Cant.', 'P. unitario', 'Importe']
    rows = [[small(x) for x in headers]]
    for item in items:
        rows.append([
            small(item.description),
            small(item.quantity),
            small(_money(item.unit_price, contract.currency)),
            small(_money(item.total, contract.currency)),
        ])
    if not items:
        rows.append([small('Sin conceptos registrados'), '', '', ''])
    table = Table(rows, colWidths=[82*mm, 18*mm, 36*mm, 36*mm], repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EEF2F7')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, 0), .7, LINE),
        ('LINEBELOW', (0, 1), (-1, -1), .3, LINE),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.append(table)
    story.append(Spacer(1, 5*mm))
    totals = [
        ('Subtotal', contract.subtotal),
        ('Descuentos', contract.discount_total),
        ('Impuestos', contract.tax_total),
        ('TOTAL', contract.total),
    ]
    for label, amount in totals:
        story.append(Paragraph(f'<b>{_p(label)}:</b> {_p(_money(amount, contract.currency))}', styles['ContractRightX']))

    story.append(Paragraph('4. Condiciones comerciales', styles['ContractHeadingX']))
    story.append(body(_value(contract, 'terms_conditions', default='No se registraron condiciones comerciales.')))
    if contract.notes:
        story.append(Paragraph('5. Observaciones', styles['ContractHeadingX']))
        story.append(body(contract.notes))
    story.append(Spacer(1, 15*mm))
    signatures = Table([
        [small('________________________________'), small('________________________________')],
        [small('Representante de la empresa'), small('Cliente / Contratante')],
        [small('Nombre y firma'), small('Nombre y firma')],
    ], colWidths=[86*mm, 86*mm], hAlign='CENTER')
    signatures.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
    story.append(KeepTogether(signatures))
    story.append(Spacer(1, 7*mm))
    story.append(Paragraph('Documento generado electrónicamente. Los espacios de firma no constituyen una firma electrónica.', styles['ContractSmallX']))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(19*mm, 12*mm, 'Eventos SaaS · Documento contractual')
        canvas.drawRightString(191*mm, 12*mm, f'Página {document.page}')
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buffer.seek(0)
    return buffer
