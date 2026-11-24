"""BRAND-01: identidad EasiAcc en la plataforma; identidad del tenant en sus documentos."""
import re
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select

from app.branding import BRAND_NAME, PRODUCT_NAME, tenant_display_name
from app.extensions import db
from app.models import Tenant
from app.models.company_receipt import CompanyReceiptSettings
from tests.test_identity import client, register  # noqa: F401

APP_DIR = Path(__file__).resolve().parent.parent / "app"


def test_no_legacy_brand_and_correct_spelling():
    for path in APP_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "Eventos SaaS" not in text, f"marca anterior en {path}"
        if path.name != "branding.py":  # solo branding.py documenta la regla de escritura
            assert not re.search(r"EasyAcc", text, re.IGNORECASE), f"«EasyAcc» mal escrito en {path}"
    assert BRAND_NAME == "EasiAcc" and PRODUCT_NAME == "EasiAcc Events"


def test_tenant_display_name_prefers_commercial_name(client):
    tenant_id = register(client, "brand@example.test", "brand-co").json["tenant_id"]
    with client.application.app_context():
        assert tenant_display_name(tenant_id) == db.session.get(Tenant, tenant_id).name
        db.session.add(CompanyReceiptSettings(tenant_id=tenant_id, commercial_name="  Banquetes Lupita  "))
        db.session.commit()
        assert tenant_display_name(tenant_id) == "Banquetes Lupita"
        assert tenant_display_name(999999) == ""


def test_platform_emails_use_easiacc(client):
    register(client, "mail-brand@example.test", "mail-brand")
    with patch("app.api.auth.send_email") as send:
        client.post("/api/v1/auth/password/forgot", json={"email": "mail-brand@example.test"})
    kwargs = send.call_args.kwargs
    assert kwargs["subject"] == "Restablece tu contraseña de EasiAcc"
    assert "EasiAcc — Simplifica tu negocio." in kwargs["text_body"]


def test_member_invitation_names_company_and_product(client):
    r = register(client, "inv-brand@example.test", "inv-brand")
    token = client.post("/api/v1/auth/login", json={"email": "inv-brand@example.test", "password": "a-very-long-password"}).json["access_token"]
    headers = {"Authorization": "Bearer " + token, "X-Tenant-ID": str(r.json["tenant_id"])}
    with client.application.app_context():
        name = db.session.get(Tenant, r.json["tenant_id"]).name
    with patch("app.api.members.send_email") as send:
        client.post("/api/v1/invitations", headers=headers, json={"email": "x@example.test", "role": "staff"})
    kwargs = send.call_args.kwargs
    assert kwargs["subject"] == f"Te invitaron a {name} en EasiAcc Events"
    assert name in kwargs["text_body"]


def test_mercadopago_reason_uses_product_name(client):
    from decimal import Decimal
    from app.models.billing import BillingPlan, BillingPlanPrice
    r = register(client, "mp-brand@example.test", "mp-brand")
    token = client.post("/api/v1/auth/login", json={"email": "mp-brand@example.test", "password": "a-very-long-password"}).json["access_token"]
    headers = {"Authorization": "Bearer " + token, "X-Tenant-ID": str(r.json["tenant_id"])}
    client.application.config.update(MP_ACCESS_TOKEN="t", MP_BACK_URL="https://example.test/billing/return")
    with client.application.app_context():
        plan = BillingPlan(code="brand-basic", name="Básico", active=True)
        db.session.add(plan); db.session.flush()
        price = BillingPlanPrice(plan_id=plan.id, currency="MXN", billing_interval="month", amount=Decimal("299"), active=True)
        db.session.add(price); db.session.commit()
        price_id = price.id
    with patch("app.services.billing.mercadopago_service.api", return_value={"id": "mp-b", "init_point": "https://mp.example/b"}) as api:
        assert client.post("/api/v1/billing/mercadopago/checkout", headers=headers,
                           json={"plan_price_id": price_id, "payer_email": "b@example.test"}).status_code == 201
    assert api.call_args.args[2]["reason"] == "EasiAcc Events - Básico"
