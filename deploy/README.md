# Despliegue — Opción A (un servidor + MySQL administrado)

> Proveedor elegido: **Linode (Akamai Cloud)**. Guía paso a paso: [`LINODE.md`](LINODE.md).

Probado de extremo a extremo en local el 2026-11-23 con las imágenes de producción: Caddy (TLS) → nginx
(frontend) → gunicorn (backend) → MySQL 8 + Redis. Probados: script de despliegue, migraciones, siembra,
cabeceras de seguridad, CSP en navegador, límite de intentos por IP real, rechazo de webhooks sin firma,
backup y restauración.

```
Internet ──443──> caddy (Let's Encrypt) ──> frontend:8080 (nginx, SPA + /api) ──> backend:5000 (gunicorn)
                                                                                    ├─> redis (rate limiting)
                                                                                    ├─> volumen uploads
                                                                                    └─> MySQL administrado (TLS)
```

## Recursos a contratar (requieren tu aprobación; no se ha creado nada)

| Recurso | Tamaño mínimo sugerido |
|---|---|
| Servidor Ubuntu 24.04 | 2 vCPU, 4 GB RAM, 50 GB SSD, IP fija |
| MySQL 8 administrado | Plan básico con backups automáticos diarios y PITR, mismo proveedor y región |
| Dominio | Registro A `app.tu-dominio.com` → IP del servidor (y `staging.tu-dominio.com`) |
| Almacenamiento externo de backups (opcional, recomendado) | Bucket S3/B2 configurado en `rclone` |

Staging: un segundo servidor pequeño (1 vCPU / 2 GB) o el mismo con otro `STACK_NAME`, siempre con **otra
base de datos y credenciales de PRUEBA de Mercado Pago**.

## 1. Preparar el servidor (una vez)

```bash
scp -r deploy root@SERVIDOR:/opt/eventos/
ssh root@SERVIDOR 'bash /opt/eventos/deploy/scripts/bootstrap-server.sh'
```

Instala Docker, firewall (solo 22/80/443), actualizaciones automáticas, fail2ban y rclone.

## 2. Base de datos administrada

En la consola del proveedor: crear `eventos_saas_prod` (utf8mb4), un usuario de aplicación con permisos solo
sobre esa base y un usuario de backup (SELECT, LOCK TABLES, SHOW VIEW, TRIGGER, EVENT). Permitir conexiones
solo desde la IP del servidor.

## 3. Configuración

```bash
cd /opt/eventos/deploy
cp env/stack.env.example env/stack.env && cp env/backend.env.example env/backend.env
chmod 600 env/*.env && nano env/stack.env env/backend.env
```

Si las imágenes de GHCR son privadas: `docker login ghcr.io` con un token de GitHub con `read:packages`.

## 4. Publicar imágenes y desplegar

1. En GitHub, crear el tag `v1.0.0` en ambos repositorios (tras fusionar los PR). El workflow
   `Release image` publica `ghcr.io/jesuspayan/<repo>:v1.0.0`.
2. En el servidor:
   ```bash
   cd /opt/eventos/deploy
   scripts/deploy.sh v1.0.0      # backup -> pull -> migraciones -> arranque -> verificación https
   docker compose --env-file env/stack.env exec backend \
     python -m scripts.seed_billing_catalog --allow-production --confirm-database eventos_saas_prod
   ```
3. Registrar la cuenta del operador en la app, poner su `users.id` en `BILLING_OPERATOR_USER_IDS` y volver a
   ejecutar `scripts/deploy.sh`.
4. Configurar el webhook de Mercado Pago (`docs/MERCADOPAGO.md`).
5. Instalar tareas programadas: `cp scripts/crontab.example /etc/cron.d/eventos`.

## Operación

| Acción | Comando |
|---|---|
| Nueva versión | `scripts/deploy.sh v1.0.1` |
| Rollback | `scripts/deploy.sh v1.0.0` (las migraciones v1 son aditivas) |
| Backup manual | `scripts/backup.sh` |
| Probar restauración | `scripts/restore-check.sh /var/backups/eventos/<fecha>` |
| Logs | `docker compose --env-file env/stack.env logs -f backend` |
| Estado | `docker compose --env-file env/stack.env ps` |
