"""Usage: python -m scripts.reconcile_mercadopago [--apply] [--limit 100]
Dry-run is the default. Run via a scheduler with a single-worker lock.
"""
import argparse
import json
from app import create_app
from app.services.billing.mercadopago_reconciliation import reconcile_known


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Perform provider calls and persist reconciliation')
    parser.add_argument('--limit', type=int, default=100)
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        result = reconcile_known(apply=args.apply, limit=args.limit)
    print(json.dumps(result, ensure_ascii=False))
    if result['failed'] or result['unmatched']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
