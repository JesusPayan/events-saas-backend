"""Identidad comercial de la plataforma (EasiAcc) y de cada empresa cliente.

La marca de la PLATAFORMA (EasiAcc) identifica la herramienta. Los documentos y
comunicaciones dirigidos a los clientes de cada empresa usan la identidad de esa
empresa (tenant_display_name); EasiAcc aparece solo como «generado/enviado con».
Escribir siempre «EasiAcc» (nunca «EasyAcc»).
"""
import os

BRAND_NAME = os.getenv("BRAND_NAME", "EasiAcc")
PRODUCT_NAME = os.getenv("PRODUCT_NAME", "EasiAcc Events")
BRAND_TAGLINE = os.getenv("BRAND_TAGLINE", "Simplifica tu negocio.")
PUBLIC_WEBSITE_URL = os.getenv("PUBLIC_WEBSITE_URL", "https://easiacc.com")

# Firma de correos de la plataforma.
EMAIL_SIGNATURE = f"{BRAND_NAME} — {BRAND_TAGLINE}"


def tenant_display_name(tenant_id):
    """Nombre comercial de la empresa (configuración de comprobantes) o el de su cuenta."""
    from app.extensions import db
    from app.models import Tenant
    from app.models.company_receipt import CompanyReceiptSettings
    settings = db.session.get(CompanyReceiptSettings, tenant_id)
    if settings is not None and settings.commercial_name and settings.commercial_name.strip():
        return settings.commercial_name.strip()
    tenant = db.session.get(Tenant, tenant_id)
    return tenant.name if tenant is not None else ""
