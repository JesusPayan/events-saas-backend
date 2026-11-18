from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from app.services.payment_receipt_service import generate_receipt_pdf, receipt_number


def test_receipt_pdf_is_generated_without_writes():
    contract = SimpleNamespace(contract_number='CON-TEST', currency='MXN')
    payment = SimpleNamespace(id=123, amount=Decimal('1000.00'), currency='MXN',
        payment_type='advance', payment_method='bank_transfer', reference='REF-1',
        confirmed_at=datetime(2026, 11, 18, 8, 0), created_at=datetime(2026, 11, 18, 7, 0))
    tenant = SimpleNamespace(name='Empresa de prueba')
    client = SimpleNamespace(client_type='individual', first_name='Cliente', last_name='Prueba', business_name=None)
    pdf = generate_receipt_pdf(contract, payment, tenant, client)
    assert pdf.startswith(b'%PDF-')
    assert len(pdf) > 1000
    assert receipt_number(payment.id) == 'REC-0000000123'
