# Despliegue de producción

> Propuesta. No se ha creado ningún recurso en la nube ni se ha incurrido en costos.
> Las decisiones de proveedor y presupuesto requieren tu aprobación.

## Arquitectura recomendada (mínima viable y reproducible)

```
Usuarios ──HTTPS──> [Proxy TLS / CDN]  (Cloudflare o balanceador del proveedor)
                         │
                         ▼
                 frontend (nginx, imagen del repo event-saas-frontend, :8080)
                   ├── /            → Angular compilado (SPA)
                   └── /api/*       → backend:5000 (mismo origen, sin CORS en el navegador)
                         │
                         ▼
                 backend (gunicorn wsgi:app, imagen de este repo, :5000)
                   ├── MySQL 8 administrado (TLS, backups automáticos, PITR)
                   ├── Redis (rate limiting compartido entre workers)
                   └── Volumen persistente /data/uploads (contratos y firmas)

Mercado Pago ──webhook HTTPS──> https://<dominio>/api/v1/billing/mercadopago/webhook
```

Opciones razonables (elige una):

| Opción | Cómputo | MySQL | Comentario |
|---|---|---|---|
| **A (elegida el 2026-11-23)** | 1 VM (2 vCPU / 4 GB) con Docker Compose | MySQL administrado del mismo proveedor | Simple, barata, reproducible. Implementada en `deploy/` |
| B | Plataforma de contenedores administrada (App Platform, Cloud Run, ECS) | MySQL administrado | Menos operación, revisar volumen persistente para uploads (usar almacenamiento de objetos) |

Requisitos indispensables en cualquier opción: dominio propio, TLS válido, MySQL con backups automáticos y
retención ≥ 7 días, volumen o bucket persistente para `/data/uploads`, Redis para rate limiting.

## Implementación de la opción A

La configuración real y el manual paso a paso están en `deploy/README.md` (Caddy con TLS automático,
scripts de despliegue, backup, prueba de restauración y tareas programadas). El ejemplo siguiente se
conserva como referencia conceptual.

## Ejemplo docker-compose (opción A)

```yaml
services:
  backend:
    image: ghcr.io/<org>/events-saas-backend:<versión>
    env_file: /etc/eventos/backend.env        # fuera del repo, permisos 600
    environment:
      FLASK_ENV: production
      TRUSTED_PROXY_COUNT: "1"                # nginx del frontend
      RATELIMIT_STORAGE_URI: redis://redis:6379/0
      UPLOAD_FOLDER_PROD: /data/uploads
    volumes: [ "uploads:/data/uploads" ]
    depends_on: [ redis ]
    restart: unless-stopped
  frontend:
    image: ghcr.io/<org>/event-saas-frontend:<versión>
    environment: { API_UPSTREAM: "http://backend:5000" }
    ports: [ "127.0.0.1:8080:8080" ]          # expuesto solo al proxy TLS
    depends_on: [ backend ]
    restart: unless-stopped
  redis:
    image: redis:7-alpine
    restart: unless-stopped
volumes:
  uploads: {}
```

El TLS se termina en el proxy (Cloudflare en modo *Full (strict)* con certificado de origen, o Caddy/nginx
con Let's Encrypt delante del puerto 8080).

## Variables de producción obligatorias

La app **no arranca** si falta alguna (`_validate_production_config`):

`FLASK_ENV=production`, `DB_URL_PROD`, `SECRET_KEY`, `JWT_SECRET_KEY`, `SIGNATURE_OTP_SECRET` (≥32 caracteres),
`MP_ACCESS_TOKEN`, `MP_WEBHOOK_SECRET`, `MP_BACK_URL` (https), `CORS_ORIGINS` (solo https),
`FRONTEND_PUBLIC_URL` (https), `RATELIMIT_STORAGE_URI` (redis://...).

Además: `SMTP_*`, `UPLOAD_FOLDER_PROD`, `BILLING_OPERATOR_USER_IDS`, `TRUSTED_PROXY_COUNT`.

Guarda los secretos en el gestor de secretos del proveedor (o un archivo fuera del repo con permisos 600).

## Primer despliegue

1. Crear base `eventos_saas_prod` (utf8mb4) y usuario con permisos solo sobre ella.
2. Ejecutar migraciones como tarea única (no al arrancar):
   `docker compose run --rm backend flask --app app:create_app db upgrade`
3. Cargar catálogo:
   `docker compose run --rm backend python -m scripts.seed_billing_catalog --allow-production --confirm-database eventos_saas_prod`
4. Registrar la cuenta del operador en la app, obtener su `users.id` y configurar `BILLING_OPERATOR_USER_IDS`.
5. Configurar webhook de Mercado Pago (ver `docs/MERCADOPAGO.md`) y ejecutar la prueba de extremo a extremo.
6. Programar conciliación diaria: `python -m scripts.reconcile_mercadopago --apply` (cron, un solo proceso).

## CI/CD

- CI existente (`.github/workflows/backend-ci.yml`): MySQL 8 + migraciones + pytest en push a `master`,
  `development`, `feature/**`, `fix/**` y PR a `master`/`development`.
- Recomendado: proteger `master` y `development` (PR obligatorio + CI verde). Hoy **no** están protegidas.
- Publicación: el workflow `Release image` construye y publica la imagen en GHCR al crear un tag `vX.Y.Z`
  (el backend solo publica si pasa la suite completa). Desplegar primero a staging y luego a producción con
  `deploy/scripts/deploy.sh <tag>`.

## Staging vs producción

Dos entornos independientes: base de datos, Redis, secretos y **aplicación de Mercado Pago** distintos
(staging con credenciales de prueba). Nunca apuntar staging a la base de producción.
