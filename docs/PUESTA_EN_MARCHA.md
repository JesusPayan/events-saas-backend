# Puesta en marcha — EasiAcc Events 1.0 (v1.1.0)

Pasos que requiere el propietario para pasar de «listo para staging» a producción. Haz todo primero en
**staging** (`staging.easiacc.com`) con credenciales de prueba de Mercado Pago y repite en producción.

**Orden recomendado:** DNS → correo → servidores → webhook → backups → monitoreo. La revisión legal (§4) puede
empezar desde hoy porque es la que más tarda.

## 1. Servidores y DNS

Sigue `deploy/LINODE.md`: cuenta de Linode, servidores, firewall, MySQL administrado, Object Storage, DNS en
Cloudflare y despliegue de `v1.1.0`.

**Correo de administración gratis:** en Cloudflare, *Email → Email Routing*, crea `admin@easiacc.com` y
`contacto@easiacc.com` con reenvío a tu correo personal. `admin@` sirve para Let's Encrypt, Linode y Mercado
Pago; `contacto@` es el correo comercial que muestra la landing y las páginas legales, así que **debe existir
antes de publicar el frontend**.

## 2. Correo transaccional

Sin esto no llegan invitaciones ni recuperaciones de contraseña.

1. **Proveedor:** Brevo o Resend. Ambos tienen plan gratuito (confirma los límites vigentes en su sitio).
2. **Verifica el dominio** `easiacc.com` en el proveedor y crea en Cloudflare los registros DNS que te indique
   (DKIM y verificación), con nube gris.
3. **SPF:** solo puede existir **un** registro TXT `v=spf1` en `@`. Si usas Email Routing, Cloudflare ya creó
   uno: agrégale el `include:` del proveedor en ese mismo registro. Ejemplo con Brevo:
   `v=spf1 include:_spf.mx.cloudflare.net include:spf.brevo.com ~all` (copia el `include` exacto que te muestre
   el proveedor).
4. **DMARC:** TXT en `_dmarc` con `v=DMARC1; p=none; rua=mailto:admin@easiacc.com`. Tras un mes sin problemas,
   sube a `p=quarantine`.
5. **Credenciales SMTP en `env/backend.env`:**

   | | Brevo | Resend |
   |---|---|---|
   | `SMTP_HOST` | `smtp-relay.brevo.com` | `smtp.resend.com` |
   | `SMTP_PORT` / `SMTP_SECURITY` | `587` / `starttls` | `587` / `starttls` |
   | `SMTP_USERNAME` | El login SMTP que muestra Brevo | `resend` |
   | `SMTP_PASSWORD` | La clave SMTP de Brevo | Tu API key |
   | `SMTP_FROM_EMAIL` | `no-reply@easiacc.com` | `no-reply@easiacc.com` |

6. **Aplica el cambio:**

   ```bash
   docker compose --env-file env/stack.env up -d --force-recreate backend
   ```

7. **Prueba:** invita desde *Miembros* a otro correo tuyo y prueba *¿Olvidaste tu contraseña?*. Deben llegar a
   la bandeja de entrada, no a spam. En Gmail, *Mostrar original* debe indicar `SPF: PASS`, `DKIM: PASS` y
   `DMARC: PASS`.

## 3. Webhook de Mercado Pago (en staging)

1. En *Mercado Pago Developers → Tus integraciones*, abre la aplicación del **vendedor de prueba**.
2. *Webhooks → Configurar notificaciones → Modo de prueba*:
   - URL: `https://staging.easiacc.com/api/v1/billing/mercadopago/webhook`
   - Eventos: **Planes y suscripciones** (`subscription_preapproval` y `subscription_authorized_payment`).
3. Copia la **clave secreta** a `MP_WEBHOOK_SECRET` y el *Access Token* de prueba del vendedor a
   `MP_ACCESS_TOKEN`; recrea el backend (comando del §2.6).
4. *Simular notificación* debe responder **200**. Revísalo en el servidor:

   ```bash
   docker compose --env-file env/stack.env logs --since 10m backend | grep -i webhook
   ```

   Si responde 401 o 403, la clave secreta no coincide.
5. **Prueba real:** en una ventana de incógnito, entra con tu usuario de EasiAcc, elige un plan y paga con el
   **comprador de prueba** y una tarjeta de prueba. **Sin ejecutar ningún script**, en 1 o 2 minutos la
   suscripción debe aparecer **activa** en *Suscripción* y en el panel global.
6. **Idempotencia:** reenvía la misma notificación desde el panel de Mercado Pago: responde 200 y
   `billing_mp_payments` sigue con una sola fila.
7. **Cancelación:** cancela desde la app; debe quedar cancelada al final del periodo y aparecer cancelada en
   Mercado Pago.
8. Si algo falla, revisa *Incidencias* en el panel global. Registra el resultado en `docs/MERCADOPAGO.md`.

**Producción:** activa las **credenciales de producción** en tu aplicación de Mercado Pago (pide datos del
negocio y la URL `https://easiacc.com`), configura el webhook en *Modo productivo* con
`https://app.easiacc.com/api/v1/billing/mercadopago/webhook` y su propia clave, y haz una suscripción real con
tu tarjeta en el plan más barato antes de abrir el registro.

## 4. Revisión legal

Con un abogado en protección de datos personales y comercio electrónico en México, a partir de los borradores
de `docs/legal/` del frontend:

1. **Aviso de privacidad** integral y simplificado conforme a la **LFPDPPP vigente** (la ley se reformó en 2025
   y cambió la autoridad: confirmar contra la versión actual).
2. **Términos y condiciones:** suscripción, renovación automática, cancelación al final del periodo, plan
   gratuito, reembolsos y limitación de responsabilidad.
3. **Encargado del tratamiento:** las empresas guardan datos de *sus* clientes en EasiAcc; normalmente se
   requiere una cláusula o contrato de encargo.
4. **Transferencias internacionales:** servidores en EE. UU. (Linode), pagos con Mercado Pago, correos con
   Brevo o Resend.
5. **Firma electrónica de contratos:** valor probatorio tal como está implementada y si conviene NOM-151.
6. **Comprobantes:** que el sistema indique claramente que no son fiscales (no son CFDI).
7. **Marca:** búsqueda en **MARCia** (IMPI) de «EasiAcc» en las clases 9, 35 y 42 y solicitud de registro.

Los textos aprobados se publican en `/privacidad` y `/terminos` del frontend.

## 5. Backups y prueba de restauración

Tres capas: *Backups* del Linode (imagen del servidor), backups del MySQL administrado y `scripts/backup.sh`
(base + archivos subidos, copia al bucket).

1. **rclone** configurado (`deploy/LINODE.md` §6) y `RCLONE_REMOTE` en `env/stack.env`.
2. **Backup manual:** debe decir `backup ok` y `copiado a ...`.

   ```bash
   /opt/eventos/deploy/scripts/backup.sh
   ```

   ```bash
   rclone ls linode:eventos-backups/staging
   ```

3. **Restauración** en un MySQL desechable (no toca la base real). Debe mostrar
   `alembic_version: b05000000001`, los conteos de tablas y `restauración OK`:

   ```bash
   /opt/eventos/deploy/scripts/restore-check.sh "$(ls -1d /var/backups/eventos/*/ | tail -1)"
   ```

4. **Simulacro de «perdí el servidor»:** restaura desde la copia del bucket y anota cuánto tardó (tu tiempo real
   de recuperación):

   ```bash
   rclone copy linode:eventos-backups/staging/<fecha> /root/simulacro
   ```

   ```bash
   /opt/eventos/deploy/scripts/restore-check.sh /root/simulacro
   ```

5. **Automatización:** `scripts/crontab.example` (copiado a `/etc/cron.d/eventos`) programa el backup diario
   (02:15 Ciudad de México), la conciliación con Mercado Pago y la prueba de restauración semanal. Revisa el log
   al día siguiente:

   ```bash
   tail -n 20 /var/log/eventos-backup.log
   ```

6. **Backups del clúster MySQL:** confirma en el panel de Linode que estén activos. No uses su botón de restaurar
   sin leer antes la documentación de Linode: puede reemplazar los datos del clúster completo.

## 6. Monitoreo externo

1. **UptimeRobot** (plan gratuito, cada 5 minutos), con alerta a `admin@easiacc.com`:

   | Tipo | URL | Qué revisa |
   |---|---|---|
   | Keyword (`ready`) | `https://app.easiacc.com/api/v1/ready` | App y base de datos |
   | HTTP(s) | `https://app.easiacc.com/api/v1/health` | Backend vivo |
   | HTTP(s) | `https://easiacc.com` | Landing |
   | HTTP(s) | `https://staging.easiacc.com/api/v1/health` | Staging (opcional) |

2. **Healthchecks.io** (gratis) para saber si el backup o la conciliación **no** corrieron: crea un check
   diario por tarea y, en `/etc/cron.d/eventos`, agrega al final de su línea
   `&& curl -fsS -m 10 https://hc-ping.com/<uuid-del-check>`.
3. **Alertas de Linode:** en cada Linode, *Settings → Alerts*, deja activas las de CPU, transferencia y disco.
   Revisa el disco cada mes con `df -h`; si se llena, `docker image prune -a` libera imágenes viejas.

## 7. Lista final antes de abrir producción

- [ ] `https://app.easiacc.com` y `https://easiacc.com` con candado; `www` redirige; `/api/v1/ready` = `ready`.
- [ ] Invitaciones y recuperación de contraseña llegan a la bandeja de entrada.
- [ ] Webhook de producción configurado y una suscripción real se activa **sola**.
- [ ] Backup en el bucket y `restore-check` aprobado.
- [ ] Monitores de UptimeRobot y Healthchecks en verde.
- [ ] Aviso de privacidad y términos aprobados y publicados.
- [ ] `contacto@easiacc.com` recibe correo.
