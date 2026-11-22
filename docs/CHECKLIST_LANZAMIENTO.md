# Checklist de lanzamiento — Eventos SaaS 1.0

Marca cada punto con evidencia (fecha, responsable, enlace a log o captura).

## Bloqueadores (todos obligatorios)

- [ ] **Rotar credenciales expuestas** en el `.env` que estuvo versionado en repos públicos: contraseña de
      aplicación de Gmail (SMTP), `JWT_SECRET_KEY`, `SECRET_KEY`, `SIGNATURE_OTP_SECRET`, `MP_WEBHOOK_SECRET`,
      `MP_ACCESS_TOKEN` y la contraseña de MySQL incluida en las URLs.
- [ ] Decidir si se reescribe el historial de Git para eliminar el `.env` (requiere force-push; la rotación
      es obligatoria de todos modos).
- [ ] Merge de la rama de endurecimiento con CI en verde (backend y frontend).
- [ ] Proteger ramas `master`/`development` (PR + CI obligatorios).
- [ ] Prueba de extremo a extremo de Mercado Pago en staging (ver `docs/MERCADOPAGO.md`), incluida la
      verificación del formato real de `authorized_payments`.
- [ ] Decisión comercial: periodo de prueba / acceso antes del primer pago, y si se activa
      `BILLING_ENFORCE_ENTITLEMENTS=true` en el lanzamiento.
- [ ] Infraestructura aprobada y creada (dominio, TLS, MySQL administrado, Redis, almacenamiento persistente).
- [ ] Backups automáticos activos y **una restauración probada** (`docs/OPERACION.md`).
- [ ] Monitoreo de `/health` y `/ready` y alertas de 5xx configurados.
- [ ] `BILLING_OPERATOR_USER_IDS` configurado con la cuenta del operador.
- [ ] Webhook de producción configurado en Mercado Pago con la clave en `MP_WEBHOOK_SECRET`.

## Verificaciones funcionales en staging

- [ ] Registro, login, selección de empresa, cierre de sesión.
- [ ] Cliente → evento → reserva de inventario → cotización (PDF) → contrato → firma → pago/comprobante.
- [ ] Logística: orden → preparación → despacho → entrega → devolución.
- [ ] Checkout, activación por webhook, pago rechazado, webhook duplicado, cancelación.
- [ ] Panel global: cambio de precio con historial; suscripción existente conserva su tarifa.
- [ ] Usuario de la empresa B no ve datos de la empresa A (probar con dos cuentas).

## Calidad

- [ ] `python -m pytest -q` en CI: todo verde.
- [ ] `npm test` y `npm run build -- --configuration production`: verdes.
- [ ] `flask db heads` muestra una sola cabeza; `db upgrade` aplicado en staging.
