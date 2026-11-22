"""Discover subscription invoices missed by webhooks.

Safe default is report-only. Applying still verifies each invoice with the
provider through reconcile_payment and existing transactional locking.
"""
from urllib.parse import urlencode
from sqlalchemy import select
from app.extensions import db
from app.models.mercadopago import MPCheckout, MPPayment
from app.services.billing.mercadopago_client import api, MPError
from app.services.billing.mercadopago_service import reconcile_payment


def discover_invoices(*, apply=False, limit=100, page_size=20, max_pages=20):
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (limit, page_size, max_pages)):
        raise ValueError('invalid_limits')
    if not (1 <= limit <= 1000 and 1 <= page_size <= 100 and 1 <= max_pages <= 100):
        raise ValueError('invalid_limits')
    checkouts = db.session.scalars(select(MPCheckout).where(
        MPCheckout.provider_subscription_id.is_not(None),
        MPCheckout.status.in_(['pending', 'authorized', 'active']),
    ).order_by(MPCheckout.id).limit(limit)).all()
    # Release read transaction before provider network calls.
    ids = [c.provider_subscription_id for c in checkouts]
    db.session.rollback()
    report = dict(mode='apply' if apply else 'dry-run', subscriptions=0, invoices=0,
                  missing=0, applied=0, rejected=0, errors=0, incomplete=0)
    seen = set()
    for provider_id in ids:
        report['subscriptions'] += 1
        complete = False
        for page in range(max_pages):
            path = '/authorized_payments/search?' + urlencode({
                'preapproval_id': provider_id, 'limit': page_size, 'offset': page * page_size,
            })
            try:
                payload = api('GET', path)
            except MPError:
                report['errors'] += 1
                break
            if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
                report['errors'] += 1
                break
            items = payload['results']
            for item in items:
                if not isinstance(item, dict) or str(item.get('preapproval_id')) != provider_id:
                    report['rejected'] += 1
                    continue
                invoice_id = item.get('id')
                if invoice_id is None or not str(invoice_id).isdigit():
                    report['rejected'] += 1
                    continue
                invoice_id = str(invoice_id)
                if (provider_id, invoice_id) in seen:
                    continue
                seen.add((provider_id, invoice_id))
                report['invoices'] += 1
                # Invoice status is not evidence of settlement; nested payment
                # must be approved, then reconcile_payment re-fetches the invoice.
                payment = item.get('payment')
                if not isinstance(payment, dict) or payment.get('status') != 'approved':
                    continue
                exists = db.session.scalar(select(MPPayment.id).where(
                    MPPayment.provider_payment_id == invoice_id))
                db.session.rollback()
                if exists:
                    continue
                report['missing'] += 1
                if apply:
                    try:
                        if reconcile_payment(invoice_id):
                            report['applied'] += 1
                        else:
                            report['rejected'] += 1
                    except MPError:
                        report['errors'] += 1
                    finally:
                        db.session.rollback()
            paging = payload.get('paging') or {}
            total = paging.get('total') if isinstance(paging, dict) else None
            if not items or len(items) < page_size or (isinstance(total, int) and (page + 1) * page_size >= total):
                complete = True
                break
        if not complete:
            report['incomplete'] += 1
    return report
