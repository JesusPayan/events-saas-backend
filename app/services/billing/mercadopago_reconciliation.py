"""BILL-03.7: reconcile known provider resource IDs only.

This does NOT discover payments absent from the local ledger/webhooks. A separate
provider-supported discovery process must be validated before production.
"""
from sqlalchemy import select
from app.extensions import db
from app.models.mercadopago import MPCheckout, MPPayment
from app.services.billing.mercadopago_service import reconcile_preapproval, reconcile_payment
from app.services.billing.mercadopago_client import MPError


def reconcile_known(*, apply=False, limit=100):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError('limit must be between 1 and 1000')
    # Always deterministic; cap the total workload.
    checkouts = db.session.scalars(select(MPCheckout).where(
        MPCheckout.provider_subscription_id.is_not(None),
        MPCheckout.status.in_(['pending', 'authorized', 'active'])
    ).order_by(MPCheckout.id).limit(limit)).all()
    remaining = max(0, limit - len(checkouts))
    payments = db.session.scalars(select(MPPayment).order_by(MPPayment.id.desc()).limit(remaining)).all() if remaining else []
    results = {'mode': 'apply' if apply else 'dry-run', 'checked': 0, 'succeeded': 0, 'failed': 0, 'unmatched': 0,
               'limitations': 'Only locally known IDs; cannot discover missed authorized payments.'}
    for kind, resource_id in ([('preapproval', c.provider_subscription_id) for c in checkouts] +
                              [('payment', p.provider_payment_id) for p in payments]):
        results['checked'] += 1
        if not apply:
            continue
        try:
            ok = reconcile_preapproval(resource_id) if kind == 'preapproval' else reconcile_payment(resource_id)
            results['succeeded' if ok else 'unmatched'] += 1
            if not ok:
                db.session.rollback()
        except MPError:
            db.session.rollback()
            results['failed'] += 1
        except Exception:
            db.session.rollback()
            raise
    return results
