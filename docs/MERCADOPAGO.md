# Mercado Pago — Suscripciones

## Flujo implementado

1. **Catálogo** (`GET /api/v1/billing/plans`): planes y precios activos desde MySQL.
2. **Checkout** (`POST /api/v1/billing/mercadopago/checkout`, permiso `billing.manage`):
   el navegador envía solo `plan_price_id` y `payer_email`. El servidor toma el importe de MySQL, crea un
   `MPCheckout` con `external_reference` único y llama `POST /preapproval` (con `X-Idempotency-Key`).
   Devuelve `init_point`; el navegador redirige a Mercado Pago.
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
   Mercado Pago lo confirma (si no, responde 502 y no cambia nada).
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

## Prueba de extremo a extremo (pendiente — requiere tus credenciales)

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
