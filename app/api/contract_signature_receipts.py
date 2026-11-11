"""Descarga y reenvío administrativo del comprobante, con aislamiento por tenant."""
from io import BytesIO
from flask import Blueprint, g, jsonify, send_file, current_app
from app.security import tenant_permission
from app.services.contract_signature_receipt_service import (
    ReceiptError, generate_signature_receipt,
)
from app.services.contract_signature_receipt_email import send_signature_receipt

bp = Blueprint('contract_signature_receipts', __name__)


@bp.get('/contracts/signature-requests/<int:request_id>/receipt')
@tenant_permission('contracts.read')
def download_receipt(request_id):
    try:
        pdf = generate_signature_receipt(tenant_id=g.tenant_id, request_id=request_id)
        response = send_file(BytesIO(pdf), mimetype='application/pdf', as_attachment=True,
                             download_name=f'comprobante-firma-{request_id}.pdf')
        response.headers['Cache-Control'] = 'no-store'
        return response
    except ReceiptError as exc:
        return jsonify(error=exc.code), exc.status


@bp.post('/contracts/signature-requests/<int:request_id>/receipt/resend')
@tenant_permission('contracts.update')
def resend_receipt(request_id):
    try:
        send_signature_receipt(tenant_id=g.tenant_id, request_id=request_id)
        return jsonify(message='Comprobante enviado.'), 200
    except ReceiptError as exc:
        return jsonify(error=exc.code), exc.status
    except Exception:
        current_app.logger.exception('Error reenviando comprobante request_id=%s', request_id)
        return jsonify(error='receipt_delivery_failed'), 502
