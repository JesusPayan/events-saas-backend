"""python -m scripts.discover_mercadopago_invoices [--apply] [--limit 100]"""
import argparse
import json
from app import create_app
from app.services.billing.mercadopago_discovery import discover_invoices


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--page-size', type=int, default=None,
                        help='Opcional; por defecto se usa el tamaño de página de Mercado Pago')
    parser.add_argument('--max-pages', type=int, default=20)
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        result = discover_invoices(apply=args.apply, limit=args.limit,
                                   page_size=args.page_size, max_pages=args.max_pages)
    print(json.dumps(result, ensure_ascii=False))
    if result['errors'] or result['incomplete'] or result['rejected']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
