# Despliegue en Linode (Akamai Cloud) — guía paso a paso

Implementa la **opción A** (`deploy/README.md`) en Linode: un servidor Ubuntu con Docker Compose más
MySQL 8 administrado. Los precios son **aproximados**: confírmalos en la página de precios de Linode antes de
crear cada recurso. No se ha creado nada todavía.

## 0. Antes de empezar

- Cuenta de Akamai Cloud (Linode) con **verificación en dos pasos** activada.
- En *Billing*, configura una **alerta de gasto** (por ejemplo, US$70/mes).
- Un dominio (por ejemplo `tumarca.com`) con DNS en Cloudflare (gratis).
- En tu PC, una **llave SSH**. En Windows (PowerShell): `ssh-keygen -t ed25519`. La llave pública queda en
  `C:\Users\<tu-usuario>\.ssh\id_ed25519.pub`.
- **Región:** elige la misma para todo. Desde México, **Dallas** o **Miami** dan buena latencia.

## Recursos y costo aproximado

| Recurso | Plan sugerido | Aprox. US$/mes |
|---|---|---|
| Linode producción | Shared CPU, 4 GB RAM, Ubuntu 24.04 | ~24 |
| Backups del Linode (complemento) | Activado | ~5 |
| Linode staging | Shared CPU, 2 GB RAM | ~12 |
| MySQL administrado | MySQL 8, plan más pequeño, 1 nodo | ~15–30 |
| Object Storage (copia externa de backups) | 1 bucket | ~5 |
| **Total** | | **~60–75** |

## 1. Crear el servidor (Linode)

*Linodes → Create Linode*:

1. **Image:** Ubuntu 24.04 LTS. **Region:** la elegida. **Plan:** Shared CPU → Linode 4 GB.
2. **Label:** `eventos-prod`.
3. **Root password:** una contraseña larga y única, guardada en tu gestor de contraseñas.
4. **SSH Keys:** agrega tu llave pública (`id_ed25519.pub`).
5. **Add-ons:** activa **Backups** y **Private IP**.
6. *Create Linode*. Anota su **IP pública**.

## 2. Firewall de Linode

*Firewalls → Create Firewall* (`eventos-fw`) y asígnalo a `eventos-prod`:

| Dirección | Protocolo | Puerto | Origen | Acción |
|---|---|---|---|---|
| Entrada | TCP | 22 | **Solo tu IP** | Aceptar |
| Entrada | TCP | 80, 443 | Todos | Aceptar |
| Entrada | UDP | 443 | Todos | Aceptar |
| Entrada | — | resto | — | **Descartar** (política por defecto) |
| Salida | — | todo | — | Aceptar |

## 3. MySQL administrado

*Databases → Create Database Cluster*:

1. **Engine:** MySQL 8. **Region:** la misma del servidor. **Plan:** el más pequeño, 1 nodo.
2. **Access controls (allowed IPs):** agrega la IP de `eventos-prod` (y su IP privada si el panel lo permite).
   No agregues `0.0.0.0/0`.
3. Al terminar, en el detalle del clúster anota **host**, **puerto** y **usuario/contraseña de administrador**, y
   descarga el certificado con **Download CA Certificate**.

Crea la base y los usuarios desde el servidor (paso 6) con el cliente de MySQL:

```sql
CREATE DATABASE eventos_saas_prod CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'eventos_app'@'%' IDENTIFIED BY '<CLAVE-LARGA-APP>' REQUIRE SSL;
GRANT ALL PRIVILEGES ON eventos_saas_prod.* TO 'eventos_app'@'%';
CREATE USER 'eventos_backup'@'%' IDENTIFIED BY '<CLAVE-LARGA-BACKUP>' REQUIRE SSL;
GRANT SELECT, LOCK TABLES, SHOW VIEW, TRIGGER, EVENT ON eventos_saas_prod.* TO 'eventos_backup'@'%';
```

Si tu plan no ofrece MySQL 8 administrado en la región elegida, escríbelo antes de seguir: la alternativa
(MySQL en un servidor propio) exige administrar backups y actualizaciones a mano.

## 4. Object Storage (copia externa de backups)

*Object Storage → Create Bucket* (`eventos-backups`, misma región) y *Access Keys → Create Access Key*,
limitada a ese bucket con lectura y escritura. Guarda la **Access Key** y la **Secret Key**.

## 5. DNS en Cloudflare

Crea un registro `A`: nombre `app`, valor la IP pública de `eventos-prod`, **Proxy: DNS only** (nube gris).
Caddy obtiene el certificado HTTPS automáticamente. Más adelante puedes activar el proxy naranja con
*SSL/TLS → Full (strict)*.

## 6. Preparar el servidor

Desde tu PC:

```bash
ssh root@IP-DEL-SERVIDOR
```

En el servidor:

```bash
git clone https://github.com/JesusPayan/events-saas-backend.git /opt/eventos/src
```

```bash
cp -r /opt/eventos/src/deploy /opt/eventos/deploy && bash /opt/eventos/deploy/scripts/bootstrap-server.sh
```

```bash
apt-get install -y mysql-client
```

Pega el certificado CA descargado en el paso 3 (ábrelo con un editor de texto y copia todo su contenido):

```bash
mkdir -p /opt/eventos/deploy/env/certs && nano /opt/eventos/deploy/env/certs/db-ca.pem
```

Crea la base y los usuarios (pega el SQL del paso 3):

```bash
mysql --host=HOST-DE-LA-BASE --port=PUERTO --user=ADMIN --password --ssl-mode=VERIFY_CA --ssl-ca=/opt/eventos/deploy/env/certs/db-ca.pem
```

Configuración:

```bash
cd /opt/eventos/deploy && cp env/stack.env.example env/stack.env && cp env/backend.env.example env/backend.env
```

```bash
chmod 600 env/*.env env/certs/db-ca.pem && nano env/stack.env env/backend.env
```

En `env/backend.env`: `DB_URL_PROD` con el host y puerto de la base, `DB_SSL_CA=/etc/eventos/certs/db-ca.pem`,
secretos generados con `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`, credenciales de
Mercado Pago y el SMTP transaccional. Si la conexión falla por el nombre del host del certificado, agrega
`DB_SSL_VERIFY_HOSTNAME=false` (se sigue verificando el CA).

Copia externa de backups con rclone (proveedor `Linode`, con la Access Key del paso 4):

```bash
rclone config
```

Después pon `RCLONE_REMOTE=<nombre-del-remoto>:eventos-backups` en `env/stack.env`.

## 7. Desplegar

Si las imágenes de GHCR son privadas, inicia sesión con un token de GitHub de solo lectura (`read:packages`):

```bash
docker login ghcr.io
```

```bash
cd /opt/eventos/deploy && scripts/deploy.sh v1.0.1
```

```bash
docker compose --env-file env/stack.env exec backend python -m scripts.seed_billing_catalog --allow-production --confirm-database eventos_saas_prod
```

```bash
cp scripts/crontab.example /etc/cron.d/eventos
```

Abre `https://app.tumarca.com`, registra la cuenta del operador, pon su `users.id` en
`BILLING_OPERATOR_USER_IDS` y vuelve a ejecutar `scripts/deploy.sh`.

## 8. Verificaciones antes de abrir a usuarios

- [ ] `https://app.tumarca.com` carga con candado y `/api/v1/ready` responde `ready`.
- [ ] `scripts/backup.sh` genera un backup y se copia al bucket.
- [ ] `scripts/restore-check.sh /var/backups/eventos/<fecha>` restaura sin errores.
- [ ] Webhook de Mercado Pago configurado con `https://app.tumarca.com/api/v1/billing/mercadopago/webhook`;
      un checkout de prueba se activa **solo**, sin script.
- [ ] Monitoreo externo (UptimeRobot) sobre `/api/v1/health` con alerta a tu correo.

## Staging

Repite los pasos 1, 2, 5 y 6 con un Linode de 2 GB (`eventos-staging`), el subdominio `staging.tumarca.com`,
`STACK_NAME=eventos-staging`, **otra base** (`eventos_saas_staging`, con sus propios usuarios, en el mismo clúster
para ahorrar) y **credenciales de prueba** de Mercado Pago.
