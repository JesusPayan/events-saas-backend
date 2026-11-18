"""Tenant-isolated download endpoint for confirmed payment receipts."""
from io import BytesIO
from flask import Blueprint, g, send_file
from app.security import tenant_permission
from app.services.payment_receipt_service import (
    ReceiptNotFound, load_receipt_data, generate_receipt_pdf, receipt_number,
)

bp = Blueprint('payment_receipts', __name__)


@bp.get('/contracts/<int:contract_id>/payments/<int:payment_id>/receipt')
@tenant_permission('contracts.read')
def download_payment_receipt(contract_id, payment_id):
    try:
        contract, payment, tenant, client = load_receipt_data(
            tenant_id=g.tenant_id, contract_id=contract_id, payment_id=payment_id,
        )
    except ReceiptNotFound:
        return {'error': 'receipt_not_available',
                'message': 'No existe un pago confirmado disponible para este contrato.'}, 404
    pdf = generate_receipt_pdf(contract, payment, tenant, client)
    response = send_file(BytesIO(pdf), mimetype='application/pdf',
                         as_attachment=True,
                         download_name=f'{receipt_number(payment.id)}.pdf')
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
