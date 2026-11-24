# Despliegue en Linode (Akamai Cloud) — guía paso a paso

Implementa la **opción A** (`deploy/README.md`) en Linode: un servidor Ubuntu con Docker Compose más
MySQL 8 administrado, con el dominio `easiacc.com` (DNS en Cloudflare). Los precios son **aproximados**:
confírmalos en la página de precios de Linode antes de crear cada recurso.

Haz todo primero en **staging** (`staging.easiacc.com`, credenciales de prueba de Mercado Pago) y repite en
producción cuando staging funcione. Lo que sigue al despliegue (correo, webhook, backups, monitoreo y revisión
legal) está en `docs/PUESTA_EN_MARCHA.md`.

## 0. Antes de empezar

- Cuenta de Akamai Cloud (Linode) con **verificación en dos pasos** activada.
- En *Billing*, configura una **alerta de gasto** (por ejemplo, US$70/mes).
- DNS de `easiacc.com` en Cloudflare (§5).
- En tu PC, una **llave SSH**. En Windows (PowerShell): `ssh-keygen -t ed25519`. La llave pública queda en
  `C:\Users\<tu-usuario>\.ssh\id_ed25519.pub`.
- **Región:** elige la misma para todo. Desde México, **Dallas** o **Miami** dan buena latencia.

## Recursos y costo aproximado

| Recurso | Staging | Producción | Aprox. US$/mes |
|---|---|---|---|
| Linode (Ubuntu 24.04, Shared CPU) | `eventos-staging`, 2 GB | `eventos-prod`, 4 GB | ~12 + ~24 |
| Backups del Linode (complemento) | — | Activado | ~5 |
| MySQL 8 administrado, 1 nodo, plan más pequeño | Un solo clúster con dos bases | (el mismo) | ~15–30 |
| Object Storage | Bucket `eventos-backups` (carpetas `staging/` y `prod/`) | (el mismo) | ~5 |
| **Total** | | | **~60–75** |

## 1. Crear los servidores (Linode)

*Linodes → Create Linode*:

1. **Image:** Ubuntu 24.04 LTS. **Region:** la elegida. **Plan:** Shared CPU → 2 GB (staging) o 4 GB
   (producción).
2. **Label:** `eventos-staging` o `eventos-prod`.
3. **Root password:** una contraseña larga y única, guardada en tu gestor de contraseñas.
4. **SSH Keys:** agrega tu llave pública (`id_ed25519.pub`).
5. **Add-ons (producción):** activa **Backups** y **Private IP**.
6. *Create Linode*. Anota su **IP pública**.

## 2. Firewall de Linode

*Firewalls → Create Firewall* (`eventos-fw`) y asígnalo a **los dos** Linode:

| Dirección | Protocolo | Puerto | Origen | Acción |
|---|---|---|---|---|
| Entrada | TCP | 22 | **Solo tu IP** | Aceptar |
| Entrada | TCP | 80, 443 | Todos | Aceptar |
| Entrada | UDP | 443 | Todos | Aceptar |
| Entrada | — | resto | — | **Descartar** (política por defecto) |
| Salida | — | todo | — | Aceptar |

## 3. MySQL administrado

*Databases → Create Database Cluster*:

1. **Engine:** MySQL 8. **Region:** la misma de los servidores. **Plan:** el más pequeño, 1 nodo.
2. **Access controls (allowed IPs):** agrega la IP de `eventos-staging` y la de `eventos-prod`.
   No agregues `0.0.0.0/0`.
3. Al terminar, en el detalle del clúster anota **host**, **puerto** y **usuario/contraseña de administrador**, y
   descarga el certificado con **Download CA Certificate**.

Crea las bases y los usuarios desde el servidor (§6) con el cliente de MySQL. **Producción:**

```sql
CREATE DATABASE eventos_saas_prod CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'eventos_app'@'%' IDENTIFIED BY '<CLAVE-LARGA-APP>' REQUIRE SSL;
GRANT ALL PRIVILEGES ON eventos_saas_prod.* TO 'eventos_app'@'%';
CREATE USER 'eventos_backup'@'%' IDENTIFIED BY '<CLAVE-LARGA-BACKUP>' REQUIRE SSL;
GRANT SELECT, LOCK TABLES, SHOW VIEW, TRIGGER, EVENT ON eventos_saas_prod.* TO 'eventos_backup'@'%';
```

**Staging** (otra base y otros usuarios, con claves distintas):

```sql
CREATE DATABASE eventos_saas_staging CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'staging_app'@'%' IDENTIFIED BY '<OTRA-CLAVE-APP>' REQUIRE SSL;
GRANT ALL PRIVILEGES ON eventos_saas_staging.* TO 'staging_app'@'%';
CREATE USER 'staging_backup'@'%' IDENTIFIED BY '<OTRA-CLAVE-BACKUP>' REQUIRE SSL;
GRANT SELECT, LOCK TABLES, SHOW VIEW, TRIGGER, EVENT ON eventos_saas_staging.* TO 'staging_backup'@'%';
```

Si tu plan no ofrece MySQL 8 administrado en la región elegida, detente antes de seguir: la alternativa
(MySQL en un servidor propio) exige administrar backups y actualizaciones a mano.

## 4. Object Storage (copia externa de backups)

*Object Storage → Create Bucket* (`eventos-backups`, misma región) y *Access Keys → Create Access Key*,
limitada a ese bucket con lectura y escritura. Guarda la **Access Key** y la **Secret Key**, y anota el
*endpoint* de la región.

## 5. DNS en Cloudflare

Si `easiacc.com` aún no está en Cloudflare: *Add a site → easiacc.com → plan Free*; copia los dos
*nameservers* que te asigna y pégalos en Namecheap (*Domain List → easiacc.com → Manage → Nameservers →
Custom DNS*). Espera a que Cloudflare marque el dominio como **Active**.

Registros **A**, todos con **Proxy: DNS only** (nube gris), para que Caddy obtenga los certificados HTTPS:

| Nombre | Valor |
|---|---|
| `staging` | IP de `eventos-staging` |
| `@` | IP de `eventos-prod` |
| `app` | IP de `eventos-prod` |
| `www` | IP de `eventos-prod` (Caddy redirige `www` al dominio sin `www`) |

Comprueba que el nombre resuelva a la IP antes de desplegar (`nslookup staging.easiacc.com`). Más adelante
puedes activar el proxy naranja con *SSL/TLS → Full (strict)*.

## 6. Preparar cada servidor

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

Pega el certificado CA descargado en el §3 (ábrelo con un editor de texto y copia todo su contenido):

```bash
mkdir -p /opt/eventos/deploy/env/certs && nano /opt/eventos/deploy/env/certs/db-ca.pem
```

Crea la base y los usuarios (pega el SQL del §3 que corresponda al servidor):

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

Valores que cambian entre entornos:

| Variable | Staging | Producción |
|---|---|---|
| `STACK_NAME` (`stack.env`) | `eventos-staging` | `eventos` |
| `DOMAIN` (`stack.env`) | `staging.easiacc.com` | `app.easiacc.com, easiacc.com, www.easiacc.com` |
| `DB_NAME`, `DB_BACKUP_USER`, `DB_BACKUP_PASSWORD` (`stack.env`) | `eventos_saas_staging`, `staging_backup` | `eventos_saas_prod`, `eventos_backup` |
| `RCLONE_REMOTE` (`stack.env`) | `linode:eventos-backups/staging` | `linode:eventos-backups/prod` |
| `DB_URL_PROD` (`backend.env`) | `…staging_app:<clave>@<host>:<puerto>/eventos_saas_staging` | `…eventos_app:<clave>@<host>:<puerto>/eventos_saas_prod` |
| `CORS_ORIGINS`, `FRONTEND_PUBLIC_URL` (`backend.env`) | `https://staging.easiacc.com` | `https://app.easiacc.com` |
| `MP_BACK_URL` (`backend.env`) | `https://staging.easiacc.com/billing/return` | `https://app.easiacc.com/billing/return` |
| `MP_ACCESS_TOKEN`, `MP_WEBHOOK_SECRET` | Credenciales **de prueba** | Credenciales de producción |

En ambos: `DB_HOST` y `DB_PORT` del clúster, `DB_SSL_CA=/etc/eventos/certs/db-ca.pem`, y `SECRET_KEY`,
`JWT_SECRET_KEY` y `SIGNATURE_OTP_SECRET` generados con
`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`: **distintos entre sí y entre entornos**.
El SMTP se configura en `docs/PUESTA_EN_MARCHA.md` §2. Si la conexión a la base falla por el nombre del host del
certificado, agrega `DB_SSL_VERIFY_HOSTNAME=false` (se sigue verificando el CA).

Copia externa de backups con rclone: *New remote* llamado `linode`, tipo **S3**, proveedor **Linode**, con la
Access Key, la Secret Key y el endpoint del §4:

```bash
rclone config
```

## 7. Desplegar

Si las imágenes de GHCR son privadas, inicia sesión con un token *classic* de GitHub con solo `read:packages`:

```bash
docker login ghcr.io -u JesusPayan
```

```bash
cd /opt/eventos/deploy && scripts/deploy.sh v1.1.0
```

Siembra el catálogo de planes (en staging, `--confirm-database eventos_saas_staging`):

```bash
docker compose --env-file env/stack.env exec backend python -m scripts.seed_billing_catalog --allow-production --confirm-database eventos_saas_prod
```

```bash
cp scripts/crontab.example /etc/cron.d/eventos
```

Abre `https://app.easiacc.com` (o `https://staging.easiacc.com`) y registra la cuenta del operador. Obtén su id
en el cliente de MySQL con `SELECT id, email FROM users;`, ponlo en `BILLING_OPERATOR_USER_IDS`, cambia
`BILLING_ENFORCE_ENTITLEMENTS=true` y vuelve a ejecutar `scripts/deploy.sh`.

## 8. Verificaciones antes de abrir a usuarios

- [ ] `https://app.easiacc.com` y `https://easiacc.com` cargan con candado; `www` redirige; `/api/v1/ready`
      responde `ready`.
- [ ] Correo transaccional con SPF, DKIM y DMARC en `PASS` (`docs/PUESTA_EN_MARCHA.md` §2).
- [ ] Webhook de Mercado Pago configurado con `https://app.easiacc.com/api/v1/billing/mercadopago/webhook`;
      un checkout de prueba se activa **solo**, sin script (`docs/PUESTA_EN_MARCHA.md` §3).
- [ ] `scripts/backup.sh` genera un backup y se copia al bucket; `scripts/restore-check.sh` restaura sin errores
      (`docs/PUESTA_EN_MARCHA.md` §5).
- [ ] Monitoreo externo sobre `/api/v1/ready` y `/api/v1/health` con alerta a tu correo
      (`docs/PUESTA_EN_MARCHA.md` §6).
