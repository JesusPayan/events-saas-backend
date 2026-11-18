"""Existing COM-03.4 URL, upgraded to immutable COM-03.5 receipts."""
from io import BytesIO
from flask import Blueprint, g, send_file, jsonify
from app.security import tenant_permission
from app.services.payment_receipt_service import ReceiptNotFound
from app.services.issued_receipt_service import get_or_issue

bp = Blueprint('payment_receipts', __name__)

@bp.get('/contracts/<int:contract_id>/payments/<int:payment_id>/receipt')
@tenant_permission('contracts.read')
def download_payment_receipt(contract_id, payment_id):
    try:
        receipt = get_or_issue(g.tenant_id, contract_id, payment_id)
    except ReceiptNotFound:
        return jsonify(error='receipt_not_available'),404
    response = send_file(BytesIO(receipt.pdf_bytes),mimetype='application/pdf',as_attachment=True,download_name=f'{receipt.folio}.pdf')
    response.headers['Cache-Control']='private, no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Receipt-SHA256']=receipt.sha256
    return response
