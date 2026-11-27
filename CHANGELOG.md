# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado semántico.
La versión técnica **1.1.0** corresponde al lanzamiento comercial **EasiAcc Events 1.0**.
Los PR citados son del repositorio backend salvo que se indique `frontend#`.

## [1.2.0] — 2026-11-27

### Seguridad
- Dependencias actualizadas por vulnerabilidades conocidas (`pip-audit`): Flask 3.1.3, Werkzeug 3.1.9,
  flask-cors 6.0.0, python-dotenv 1.2.2 y Pillow 13.0.0. `pip-audit` sin hallazgos.

### Añadido
- **Roles administrativos con alcance** (ROLES-01): dueño y administrador de plataforma, promotor y roles reservados
  (soporte, finanzas, auditoría); transferencia de propiedad sin quedar sin dueño; alta y suspensión de
  organizaciones; invitaciones a roles de plataforma; enlaces de referido y prospectos; accesos temporales de solo
  lectura concedidos por la organización; bitácora `audit_events`. Ver `docs/ROLES_Y_CATALOGO.md`.
- **Catálogo de productos y servicios** (CAT-01): categorías globales con subcategorías, proveedores por organización,
  ofertas con modalidad de precio y tipo de confirmación, partidas mixtas en cotizaciones con precio pendiente fuera
  del total, portal del proveedor y bloqueo de aceptación con pendientes.
- **Catálogo compartido entre organizaciones** (NET-01, migración `c07000000001`): ofertas compartidas por elección,
  catálogo de la red, partidas de otra organización con costo y precio de venta, solicitudes recibidas con datos del
  evento y del cliente, confirmación exclusiva de la organización proveedora y auditoría.

- Migraciones aditivas `c06000000001` y `c07000000001`; script `scripts.grant_platform_owner` para designar al primer
  dueño de plataforma.

### Cambiado
- Las organizaciones suspendidas responden `403 tenant_suspended`.
- El panel global usa permisos de plataforma; `BILLING_OPERATOR_USER_IDS` se mantiene por compatibilidad.
- `/auth/me` incluye `platform` y el estado de cada empresa; `/auth/permissions` incluye `provider_id`.

## [1.1.2] — 2026-11-25

Sin cambios en el backend; se publica con el mismo número que el frontend (el despliegue usa un único `RELEASE_TAG`).

## [1.1.1] — 2026-11-25

### Documentación
- `docs/PUESTA_EN_MARCHA.md`: pasos para correo transaccional, webhook de Mercado Pago, revisión legal, backups,
  restauración y monitoreo externo.
- `deploy/LINODE.md` y ejemplos de configuración actualizados a `easiacc.com`, staging y `v1.1.0`.

## [1.1.0] — 2026-11-24 — EasiAcc Events 1.0

### Añadido
- **Identidad EasiAcc Events** (BRAND-01, #45 / frontend#21): logos, favicon, manifiesto web, manual de marca
  y configuración centralizada (`app/branding.py`, `src/app/core/brand.ts`). Los documentos y correos al cliente
  final conservan la identidad de cada empresa, con «Generado/Enviado con EasiAcc».
- **Landing comercial** en `easiacc.com` (WEB-01, #46 / frontend#23): precios leídos de MySQL vía
  `GET /api/v1/public/plans`, capturas reales, preguntas frecuentes y páginas legales (pendientes de texto final).
- **Miembros, sesión y contraseña** (AUTH-02, #43 / frontend#20): invitaciones por correo con roles
  (Administrador, Operativo, Solo lectura), cambio de rol y desactivación; sesión persistente con renovación y
  máximo de 12 h; recuperación de contraseña de un solo uso; cambiar contraseña revoca las sesiones.
- **Plan Gratuito** y cancelación al fin del periodo pagado.
- **Panel global**: precios versionados con auditoría, suscripciones, pagos e incidencias de conciliación.
- **Despliegue opción A en Linode** (DEPLOY-02, #44): guía, TLS verificado hacia MySQL administrado,
  Caddy con HTTPS automático para `app.easiacc.com`, `easiacc.com` y redirección de `www`.
- **Resumen de inventario** recuperado (INV-DASH-01, frontend#22).
- Nombres de empresa y rol en `/auth/me` y correos/roles en `/memberships` (UI-STD-02, #42).

### Cambiado
- Pantallas base estandarizadas con Tailwind/Flowbite (frontend#19); idioma **es-MX** y moneda MXN por defecto.
- Concepto de la suscripción en Mercado Pago: «EasiAcc Events - {plan}» (solo suscripciones nuevas).

### Corregido
- Mercado Pago: el plan anual usaba `frequency_type: years` (rechazado por la API); ahora 12 meses.
- Mercado Pago: checkouts abandonados bloqueaban nuevos intentos; ahora caducan a los 30 min.
- Descubrimiento de facturas: Mercado Pago rechazaba `limit=20`; ahora usa el tamaño de página del proveedor.
- Errores del proveedor diferenciados en la UI (rechazado, mal configurado, sin respuesta) y registrados sin
  datos sensibles.
- Dashboard: no mostraba los próximos eventos (fechas sin zona horaria → 400).
- Límites contables (usuarios, clientes, eventos) de 1 se mostraban como «Incluido».
- Se dejó de versionar `app/dotenv.env` (contenía la URL local de MySQL con contraseña).

### Seguridad
- Python 3.13: contexto TLS hacia MySQL que verifica el CA del proveedor; producción exige TLS a la base.
- Backups con `VERIFY_CA` y eliminación de respaldos incompletos.

## [1.0.0] — 2026-11-23

Primera versión estabilizada (backend `9076512`, frontend `28f5f0f`): auditoría y endurecimiento de billing y
Mercado Pago (verificación del cobro aprobado, cancelación confirmada por el proveedor, idempotencia), permiso
`billing.manage`, validación de configuración de producción, cabeceras de seguridad, límite de intentos,
imágenes de producción (gunicorn, nginx), build de producción del frontend reparado e interfaz de suscripciones.
