# Mercado Pago — Suscripciones

## Flujo implementado

1. **Catálogo** (`GET /api/v1/billing/plans`): planes y precios activos desde MySQL.
2. **Checkout** (`POST /api/v1/billing/mercadopago/checkout`, permiso `billing.manage`):
   el navegador envía solo `plan_price_id` y `payer_email`. El servidor toma el importe de MySQL, crea un
   `MPCheckout` con `external_reference` único y llama `POST /preapproval` (con `X-Idempotency-Key`).
   Devuelve `init_point`; el navegador redirige a Mercado Pago.
   Si el comprador abandona el pago, el checkout pendiente caduca a los `MP_CHECKOUT_PENDING_TTL_MINUTES`
   (30 por defecto): se intenta cancelar la preaprobación y se permite un nuevo intento. Un pago tardío sobre
   el enlace viejo igualmente se concilia y activa la suscripción.
3. **Retorno** (`/billing/return` en Angular): **no** activa nada. Consulta `GET /billing/subscription` y
   `GET /billing/mercadopago/checkout/latest` hasta que el servidor confirme.
4. **Webhook** (`POST /api/v1/billing/mercadopago/webhook`):
   - Valida la firma `x-signature` (HMAC-SHA256 con `MP_WEBHOOK_SECRET`, manifiesto
     `id:<data.id>;request-id:<x-request-id>;ts:<ts>;`, ventana de 5 minutos).
   - Solo procesa `subscription_preapproval` y `subscription_authorized_payment`; el resto se ignora (200).
   - Deduplica por `(tipo, recurso, x-request-id)` con índice único.
   - **Siempre vuelve a consultar el recurso en la API** de Mercado Pago; nunca confía en el cuerpo.
5. **Conciliación de pagos** (`authorized_payment`):
   - Verifica que el `preapproval_id` corresponda a un checkout conocido (tenant + precio).
   - Verifica importe y moneda contra el precio contratado.
   - **Activa solo si el cobro subyacente `payment.status == "approved"`**. El estado de la factura
     (`processed`) no basta: indica que se intentó el cobro, no que se aprobó.
   - Renovaciones extienden desde la fecha pagada; cobros rechazados se auditan (`mp_payment_rejected`) y,
     si el periodo ya venció, la suscripción pasa a `past_due`.
   - Reembolsos/contracargos se registran y auditan; un "aprobado" tardío no revierte un reembolso.
6. **Cancelación** (`POST /api/v1/billing/mercadopago/cancel`, permiso `billing.manage`): solicita
   `PUT /preapproval/{id}` con `status=cancelled`, vuelve a leer el recurso y solo marca cancelada si
   Mercado Pago lo confirma (si no, responde 502 y no cambia nada). El acceso pagado se conserva hasta
   `current_period_end`; después se aplica el plan Gratuito.
7. **Incidencias**: webhooks que no concilian quedan en `billing_mp_reconciliation_issues` (panel global) y
   se responden con 503 para que Mercado Pago reintente.

Script de conciliación manual de recursos conocidos: `python -m scripts.reconcile_mercadopago` (dry-run por
defecto; `--apply` para ejecutar).

## Configuración

| Variable | Valor |
|---|---|
| `MP_ACCESS_TOKEN` | Access token de la aplicación (TEST- en sandbox, APP_USR- en producción) |
| `MP_WEBHOOK_SECRET` | "Clave secreta" mostrada en Tus integraciones > Webhooks |
| `MP_BACK_URL` | `https://<dominio-app>/billing/return` (debe ser https) |

En el panel de Mercado Pago (Tus integraciones > tu aplicación > Webhooks):

- URL de producción: `https://<dominio-api>/api/v1/billing/mercadopago/webhook`
- Eventos: **Planes y suscripciones** (`subscription_preapproval`, `subscription_authorized_payment`).
- Copia la clave secreta a `MP_WEBHOOK_SECRET`.

Usa una aplicación/credenciales de prueba para staging y otras de producción. Nunca mezcles tokens.
Cloudflare Tunnel solo sirve para pruebas locales; producción requiere un dominio propio con TLS.

## Evidencia en sandbox (2026-11-22, entorno local del propietario)

- Checkout Básico mensual → `201`; pago aprobado por el comprador de prueba en Mercado Pago ($299 MXN).
- La API real devolvió la factura con el objeto anidado `payment.status = "approved"` (formato validado).
- Conciliación (`scripts.discover_mercadopago_invoices --apply`): suscripción `active` por un mes,
  `billing_mp_payments` con el pago `approved` de 299.00 y auditoría `mp_payment_verified`.
- Hallazgos corregidos durante la prueba: frecuencia anual inválida (`years`), paginación de búsqueda de
  facturas (`limit` rechazado), mensajes de error del proveedor y bloqueo permanente por checkouts abandonados.
- **Pendiente:** recepción del webhook. No llegó ninguna notificación al backend; revisar la configuración del
  webhook en la aplicación del vendedor de prueba (URL del túnel, eventos y clave) y repetir la prueba.
- Si Mercado Pago responde `429 local_rate_limited`, esperar unos minutos y reintentar.

## Prueba de extremo a extremo (repetir en staging)

No pudo ejecutarse desde el entorno de desarrollo de esta entrega (sin acceso de red a Mercado Pago ni
credenciales). Debe hacerse en **staging** con credenciales de prueba y usuarios de prueba
(vendedor + comprador) de Mercado Pago:

1. Registrar empresa, contratar Básico mensual con el correo del comprador de prueba.
2. Completar el pago en Mercado Pago con tarjeta de prueba aprobada.
3. Confirmar en logs: webhook 200, `billing_mp_payments` con 1 fila, suscripción `active`,
   `subscription_audits` con `mp_payment_verified`.
4. Repetir con tarjeta rechazada: suscripción **no** se activa.
5. Reenviar el mismo webhook desde el panel de Mercado Pago: respuesta `duplicate` y sin cambios.
6. Cancelar desde "Mi suscripción": estado `canceled` y preaprobación cancelada en Mercado Pago.
7. **Validar el formato real** de `GET /authorized_payments/{id}` (objeto anidado `payment.status`).
   Si difiere de lo documentado aquí, ajustar `effective_payment_status` antes de producción.
