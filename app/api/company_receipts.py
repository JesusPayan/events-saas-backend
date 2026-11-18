"""Company branding and immutable receipt endpoints."""
from io import BytesIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from flask import Blueprint, request, jsonify, g, send_file
from sqlalchemy.exc import IntegrityError
from PIL import Image, UnidentifiedImageError

from app.extensions import db
from app.security import tenant_permission
from app.models.tenant import Tenant
from app.models.company_receipt import CompanyReceiptSettings
from app.services.payment_receipt_service import ReceiptNotFound
from app.services.issued_receipt_service import get_or_issue

bp = Blueprint('company_receipts', __name__)
FIELDS = {'commercial_name':180,'contact_email':254,'phone':40,'address':500,'tax_id':20,'timezone':64}


def serialize(settings, tenant):
    return {k:(getattr(settings,k) if settings else (tenant.timezone if k=='timezone' else None)) for k in FIELDS} | {'has_logo':bool(settings and settings.logo_bytes), 'tenant_name':tenant.name}


def get_settings():
    tenant = db.session.get(Tenant, g.tenant_id)
    return tenant, db.session.get(CompanyReceiptSettings, g.tenant_id)


@bp.get('/company/receipt-settings')
@tenant_permission('contracts.read')
def company_settings():
    tenant, settings = get_settings()
    return jsonify(serialize(settings,tenant))


@bp.patch('/company/receipt-settings')
@tenant_permission('contracts.update')
def update_company_settings():
    data=request.get_json(silent=True)
    if not isinstance(data,dict) or not data or set(data)-set(FIELDS):
        return jsonify(error='invalid_fields'),400
    for field,limit in FIELDS.items():
        if field in data and (not isinstance(data[field],str) or len(data[field].strip())>limit):
            return jsonify(error='invalid_field',field=field),400
    if 'timezone' in data:
        try: ZoneInfo(data['timezone'])
        except (ZoneInfoNotFoundError,ValueError,KeyError): return jsonify(error='invalid_timezone'),400
    if 'contact_email' in data and data['contact_email'].strip() and ('@' not in data['contact_email'] or '\n' in data['contact_email']):
        return jsonify(error='invalid_email'),400
    tenant,settings=get_settings()
    if settings is None:
        settings=CompanyReceiptSettings(tenant_id=g.tenant_id,timezone=tenant.timezone)
        db.session.add(settings)
    for field in data:
        value = data[field].strip()
        if field == 'timezone' and not value: return jsonify(error='invalid_timezone'),400
        setattr(settings, field, value or None)
    db.session.commit()
    return jsonify(serialize(settings,tenant))


@bp.put('/company/receipt-settings/logo')
@tenant_permission('contracts.update')
def upload_company_logo():
    file=request.files.get('logo')
    if not file: return jsonify(error='logo_required'),400
    data=file.stream.read(1024*1024+1)
    if not data or len(data)>1024*1024: return jsonify(error='logo_too_large'),413
    try:
        img=Image.open(BytesIO(data));img.verify()
        img=Image.open(BytesIO(data))
        if img.format not in ('PNG','JPEG') or img.width>2500 or img.height>2500 or img.width<1 or img.height<1:
            return jsonify(error='invalid_logo'),400
        img.load()
        clean=BytesIO()
        if img.format=='JPEG':
            img.convert('RGB').save(clean,format='JPEG',quality=85)
            mime='image/jpeg'
        else:
            img.convert('RGBA').save(clean,format='PNG',optimize=True)
            mime='image/png'
    except (UnidentifiedImageError,ValueError,OSError):
        return jsonify(error='invalid_logo'),400
    if clean.tell()>1024*1024: return jsonify(error='logo_too_large'),413
    tenant,settings=get_settings()
    if settings is None:
        settings=CompanyReceiptSettings(tenant_id=g.tenant_id,timezone=tenant.timezone)
        db.session.add(settings)
    settings.logo_bytes=clean.getvalue();settings.logo_mime=mime
    db.session.commit()
    return jsonify(message='logo_updated'),200


@bp.get('/company/receipt-settings/logo')
@tenant_permission('contracts.read')
def download_company_logo():
    _,settings=get_settings()
    if not settings or not settings.logo_bytes: return jsonify(error='logo_not_found'),404
    resp=send_file(BytesIO(settings.logo_bytes),mimetype=settings.logo_mime)
    resp.headers['Cache-Control']='private, no-store'
    resp.headers['X-Content-Type-Options']='nosniff'
    return resp


@bp.delete('/company/receipt-settings/logo')
@tenant_permission('contracts.update')
def delete_company_logo():
    _,settings=get_settings()
    if settings:
        settings.logo_bytes=None;settings.logo_mime=None
        db.session.commit()
    return '',204

