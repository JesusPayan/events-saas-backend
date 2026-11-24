# Checklist de lanzamiento — EasiAcc Events 1.0 (v1.1.0)

Estado detallado y riesgos: `docs/PROJECT_STATUS.md`. Pasos para cada bloqueador: `docs/PUESTA_EN_MARCHA.md`. Rollback: `docs/ROLLBACK.md`.

Marca cada punto con evidencia (fecha, responsable, enlace a log o captura).

## Bloqueadores (todos obligatorios)

- [x] **Rotar credenciales expuestas** (confirmado por el propietario el 2026-11-23) en el `.env` que estuvo versionado en repos públicos: contraseña de
      aplicación de Gmail (SMTP), `JWT_SECRET_KEY`, `SECRET_KEY`, `SIGNATURE_OTP_SECRET`, `MP_WEBHOOK_SECRET`,
      `MP_ACCESS_TOKEN` y la contraseña de MySQL incluida en las URLs.
- [ ] Decidir si se reescribe el historial de Git para eliminar el `.env` (requiere force-push; la rotación
      es obligatoria de todos modos).
- [x] Ramas de endurecimiento, marca (BRAND-01), landing (WEB-01), miembros (AUTH-02) y despliegue (DEPLOY-02) fusionadas con CI en verde.
- [ ] Fusionar `development` en `master` (QA-RELEASE-01) y crear el tag `v1.1.0` desde el PC del propietario.
- [ ] Proteger ramas `master`/`development` (PR + CI obligatorios).
- [x] Pago real en sandbox: checkout, cobro aprobado, verificación del formato de `authorized_payments` y
      activación (2026-11-22, ver `docs/MERCADOPAGO.md`).
- [ ] Recepción del webhook de Mercado Pago (no llegó en la prueba local) y repetición completa en staging.
- [x] Decisión comercial (2026-11-23): sin pago, nivel **Gratuito** con funciones básicas; al cancelar se
      conserva el acceso hasta el final del periodo pagado.
- [ ] Sembrar el nivel gratuito (`scripts.seed_billing_catalog`) **antes** de activar
      `BILLING_ENFORCE_ENTITLEMENTS=true`; si no existe, las empresas sin pago quedan bloqueadas.
- [ ] Confirmar los límites del plan Gratuito (por defecto: 1 usuario, 25 clientes, 10 eventos, inventario,
      cotizaciones y contratos; sin reportes avanzados ni API).
- [x] Arquitectura elegida: opción A en **Linode** (servidor + Docker Compose + MySQL administrado), probada en local (`deploy/`, `deploy/LINODE.md`).
- [x] Dominio `easiacc.com` (Namecheap) con DNS en Cloudflare; registros en `docs/DNS_CONFIGURATION.md`.
- [x] Proveedor (Linode) y dominio (`easiacc.com`) elegidos.
- [ ] Presupuesto aprobado y recursos de staging y producción creados.
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

- [x] `python -m pytest -q` en CI: todo verde (396 pruebas, 2026-11-24).
- [x] `npm test` y `npm run build -- --configuration production`: verdes (17 pruebas, 2026-11-24).
- [x] `flask db heads` muestra una sola cabeza (`b05000000001`); migraciones probadas desde base vacía.
- [ ] `db upgrade` aplicado en staging.

## Marca y sitio comercial

- [x] Identidad EasiAcc Events aplicada (logos, favicon, correos, PDF) — `frontend/docs/BRAND_GUIDELINES.md`.
- [x] Landing en `easiacc.com` con precios desde MySQL.
- [x] Correo de contacto comercial en `BRAND.contactEmail` (`contacto@easiacc.com`; el buzón debe existir antes de publicar).
- [ ] Aviso de privacidad y términos aprobados por abogado y publicados (`frontend/docs/legal/`).
- [ ] Búsqueda y solicitud de registro de la marca EasiAcc en el IMPI.
