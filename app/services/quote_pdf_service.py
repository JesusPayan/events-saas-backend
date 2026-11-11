
from io import BytesIO
from decimal import Decimal
from html import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)


STATUS_LABELS = {
    "draft": "Borrador",
    "sent": "Enviada",
    "accepted": "Aceptada",
    "rejected": "Rechazada",
    "expired": "Vencida",
    "cancelled": "Cancelada",
    "converted": "Convertida",
}


def safe(value):
    return escape(str(value)) if value is not None else ""


def currency(value):
    amount = Decimal(str(value or 0))
    return f"${amount:,.2f} MXN"


def client_name(client):
    if client.business_name:
        return client.business_name

    return " ".join(
        part for part in (
            client.first_name,
            client.last_name,
        )
        if part
    )


def generate_quote_pdf(quote, tenant, client, event):
    buffer = BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=(210 * mm, 297 * mm),
        rightMargin=17 * mm,
        leftMargin=17 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Cotizacion {quote.quote_number}",
    )

    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="QuoteTitle",
        parent=styles["Heading1"],
        fontSize=19,
        leading=24,
        textColor=colors.HexColor("#1D4ED8"),
        spaceAfter=10,
    ))

    styles.add(ParagraphStyle(
        name="QuoteSmall",
        parent=styles["Normal"],
        fontSize=8,
        leading=12,
    ))

    styles.add(ParagraphStyle(
        name="QuoteCell",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
    ))

    styles.add(ParagraphStyle(
        name="QuoteRight",
        parent=styles["QuoteCell"],
        alignment=TA_RIGHT,
    ))

    story = []

    story.append(
        Paragraph(safe(tenant.name), styles["QuoteTitle"])
    )

    story.append(
        Paragraph(
            f"<b>COTIZACIÓN:</b> {safe(quote.quote_number)}",
            styles["Normal"],
        )
    )

    story.append(
        Paragraph(
            "<b>Estado:</b> "
            + safe(STATUS_LABELS.get(quote.status, quote.status)),
            styles["Normal"],
        )
    )

    story.append(Spacer(1, 9 * mm))

    story.append(Paragraph(
        "<b>DATOS DEL CLIENTE</b>",
        styles["Heading3"],
    ))

    client_lines = [
        client_name(client),
        client.email,
        client.phone,
        ", ".join(filter(None, [
            client.address,
            client.city,
            client.state,
            client.postal_code,
        ])),
    ]

    for line in client_lines:
        if line:
            story.append(
                Paragraph(safe(line), styles["Normal"])
            )

    story.append(Spacer(1, 7 * mm))

    story.append(Paragraph(
        "<b>DATOS DEL EVENTO</b>",
        styles["Heading3"],
    ))

    story.append(Paragraph(
        f"<b>Evento:</b> {safe(event.name)}",
        styles["Normal"],
    ))

    story.append(Paragraph(
        f"<b>Inicio:</b> {event.starts_at:%d/%m/%Y %H:%M}",
        styles["Normal"],
    ))

    story.append(Paragraph(
        f"<b>Fin:</b> {event.ends_at:%d/%m/%Y %H:%M}",
        styles["Normal"],
    ))

    if event.location:
        story.append(Paragraph(
            f"<b>Ubicación:</b> {safe(event.location)}",
            styles["Normal"],
        ))

    if quote.valid_until:
        story.append(Paragraph(
            f"<b>Vigencia:</b> {quote.valid_until:%d/%m/%Y}",
            styles["Normal"],
        ))

    story.append(Spacer(1, 8 * mm))

    headers = [
        "Concepto",
        "Cant.",
        "P. unitario",
        "Desc.",
        "Impuesto",
        "Total",
    ]

    rows = [[
        Paragraph(f"<b>{h}</b>", styles["QuoteCell"])
        for h in headers
    ]]

    for item in sorted(
        quote.items,
        key=lambda x: (x.sort_order, x.id),
    ):
        rows.append([
            Paragraph(
                safe(item.description),
                styles["QuoteCell"],
            ),
            Paragraph(
                safe(item.quantity),
                styles["QuoteRight"],
            ),
            Paragraph(
                currency(item.unit_price),
                styles["QuoteRight"],
            ),
            Paragraph(
                currency(item.discount_amount),
                styles["QuoteRight"],
            ),
            Paragraph(
                currency(item.tax_amount),
                styles["QuoteRight"],
            ),
            Paragraph(
                currency(item.total),
                styles["QuoteRight"],
            ),
        ])

    table = Table(
        rows,
        colWidths=[
            59 * mm,
            16 * mm,
            27 * mm,
            23 * mm,
            23 * mm,
            28 * mm,
        ],
        repeatRows=1,
        hAlign="LEFT",
    )

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0),
         colors.HexColor("#DBEAFE")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, 0),
         0.7, colors.HexColor("#93C5FD")),
        ("LINEBELOW", (0, 1), (-1, -1),
         0.3, colors.HexColor("#E5E7EB")),
    ]))

    story.append(table)
    story.append(Spacer(1, 7 * mm))

    summary_rows = [
        ["Subtotal", currency(quote.subtotal)],
        ["Descuentos", currency(quote.discount_total)],
        ["Impuestos", currency(quote.tax_total)],
        ["TOTAL", currency(quote.total)],
    ]

    summary = Table(
        summary_rows,
        colWidths=[38 * mm, 42 * mm],
        hAlign="RIGHT",
    )

    summary.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, -1), (-1, -1),
         colors.HexColor("#1D4ED8")),
        ("LINEABOVE", (0, -1), (-1, -1),
         0.8, colors.HexColor("#CBD5E1")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))

    story.append(summary)

    extra = []

    if quote.notes:
        extra.extend([
            Paragraph("<b>Observaciones</b>", styles["Heading3"]),
            Paragraph(
                safe(quote.notes).replace("\n", "<br/>"),
                styles["Normal"],
            ),
            Spacer(1, 4 * mm),
        ])

    if quote.terms_conditions:
        extra.extend([
            Paragraph(
                "<b>Términos y condiciones</b>",
                styles["Heading3"],
            ),
            Paragraph(
                safe(quote.terms_conditions).replace("\n", "<br/>"),
                styles["Normal"],
            ),
        ])

    if extra:
        story.append(Spacer(1, 8 * mm))
        story.extend(extra)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(
            17 * mm,
            12 * mm,
            f"Documento generado por {tenant.name}"[:90],
        )
        canvas.drawRightString(
            193 * mm,
            12 * mm,
            f"Página {doc.page}",
        )
        canvas.restoreState()

    document.build(
        story,
        onFirstPage=footer,
        onLaterPages=footer,
    )

    buffer.seek(0)
    return buffer
