# Eventos SaaS — Backend (Flask)

API REST multiempresa (multi-tenant) para gestión de eventos: clientes, eventos, inventario, logística,
cotizaciones, contratos con firma electrónica, pagos/comprobantes y suscripciones con Mercado Pago.

- Python 3.13 · Flask 3.1 · SQLAlchemy 2 · Flask-Migrate/Alembic · MySQL 8
- Aislamiento por tenant: cada endpoint de negocio exige `Authorization: Bearer <token>` y `X-Tenant-ID`,
  y valida membresía + permiso (`app/security.py`).
- Frontend: repositorio `event-saas-frontend` (Angular 20).

## Instalación local (Windows / Conda)

```cmd
conda activate crm_events
cd C:\DEV\crm-events\eventos-saas\events-saas-backend
python -m pip install -r requirements-ci.txt
copy .env.example .env
```

Edita `.env` (ver comentarios en `.env.example`). La base `crm_events_dev` debe existir en MySQL 8.

```cmd
set FLASK_ENV=development
python -m flask --app app:create_app db upgrade
python -m scripts.seed_billing_catalog
python -m flask --app app:create_app run --port 5000
```

## Pruebas

Requieren MySQL con la base `crm_events_test` (nunca la de desarrollo):

```cmd
set FLASK_ENV=test
python -m flask --app app:create_app db upgrade
python -m flask --app app:create_app run --port 5001 --no-reload
python -m pytest -q
```

(El servidor en 5001 lo usan algunas pruebas de integración vía `API_BASE_URL`.)

## Migraciones

```cmd
python -m flask --app app:create_app db heads     REM debe haber una sola cabeza
python -m flask --app app:create_app db upgrade
```

Las migraciones son aditivas. Antes de aplicar en producción: respaldo (ver `docs/OPERACION.md`).

## Producción

Nunca `flask run` ni `main.py`. Se usa `gunicorn -c gunicorn.conf.py wsgi:app` (ver `Dockerfile`).
`FLASK_ENV=production` valida al arrancar secretos, Mercado Pago, CORS https y rate limiting compartido;
si algo falta, la app no arranca.

## Documentación

| Documento | Contenido |
|---|---|
| `docs/AUDITORIA_V1.md` | Estado real, hallazgos y backlog priorizado |
| `docs/DESPLIEGUE.md` | Arquitectura de producción, variables, CI/CD, staging |
| `docs/MERCADOPAGO.md` | Configuración de suscripciones y webhooks, prueba de extremo a extremo |
| `docs/OPERACION.md` | Backups, restauración, rollback, monitoreo |
| `docs/MANUAL_OPERADOR.md` | Panel global: precios, suscripciones, conciliación |
| `docs/MANUAL_USUARIO.md` | Guía básica para empresas |
| `docs/CHECKLIST_LANZAMIENTO.md` | Criterios de salida a producción |
