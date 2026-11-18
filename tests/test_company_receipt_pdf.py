from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from app.services.issued_receipt_service import render_pdf, local_date


def test_local_date_mazatlan():
    assert local_date(datetime(2026,11,18,8,23),'America/Mazatlan') == '18/11/2026 01:23'


def test_branded_receipt_pdf():
    contract=SimpleNamespace(contract_number='CON-TEST',currency='MXN')
    payment=SimpleNamespace(id=123,amount=Decimal('1000'),currency='MXN',payment_type='advance',payment_method='bank_transfer',reference='REF',confirmed_at=datetime(2026,11,18,8,23),created_at=datetime(2026,11,18,8,0))
    tenant=SimpleNamespace(name='Empresa',timezone='America/Mazatlan')
    client=SimpleNamespace(client_type='individual',first_name='Cliente',last_name='Prueba',business_name=None)
    settings=SimpleNamespace(commercial_name='Marca',phone='6691234567',contact_email='correo@example.com',tax_id=None,address='Mazatlan',timezone='America/Mazatlan',logo_bytes=None)
    pdf=render_pdf(contract,payment,tenant,client,settings)
    assert pdf.startswith(b'%PDF-') and len(pdf)>1000
