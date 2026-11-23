# Auditoría y estado — Eventos SaaS 1.0

Fecha: 2026-11-22. Ramas auditadas: backend `development` (7331c07) + `master` (BILL-02);
frontend `feature/billing_3.5` (0173d5d). Rama de trabajo local: `release/v1.0-hardening` en ambos repos
(sin commit ni push: pendiente de autorización).

## 1. Estado real verificado

| Verificación | Antes | Después |
|---|---|---|
| Backend `pytest` (MySQL 8.0.46 real) | 334 pasan | **367 pasan** (334 + 7 de BILL-02 + 26 nuevas) |
| Migraciones desde cero | 30, una cabeza | 31, una cabeza (`b04000000001`); upgrade → downgrade → upgrade verificado |
| Frontend `ng build --configuration production` | **Falla** (13 errores en `app.routes.ts`) | Compila; paquete inicial 559 kB → 413 kB |
| Frontend `npm test` | 3 pasan | 8 pasan |
| Imagen Docker backend | Rota (`wsgi.py` y `gunicorn` inexistentes) | `wsgi.py` + `gunicorn.conf.py` + usuario no root |
| Imagen Docker frontend | Ejecutaba `ng serve` (desarrollo) | Build multi-etapa servido con nginx |
| Prueba en navegador (Playwright) | — | Registro, login, tenant, catálogo, checkout (error controlado), panel global, reprecio, aviso de límite de plan |

## 2. Hallazgos críticos

1. **Secretos expuestos**: `.env` versionado en dos repositorios **públicos** con contraseña de aplicación de
   Gmail, `JWT_SECRET_KEY`, `SIGNATURE_OTP_SECRET`, `MP_WEBHOOK_SECRET` y URL de BD con contraseña.
   Corregido en el índice (`git rm --cached`), **pero siguen en el historial**: rotación obligatoria.
2. **Activación de suscripción con cobro no aprobado**: se aceptaba `authorized_payment.status == "processed"`
   como pago aprobado. Ahora se exige `payment.status == "approved"` (fail-closed).
3. **Frontend no compilaba** en la rama de billing (rutas fuera del layout, archivos con contenido cruzado,
   componentes inexistentes).
4. **Sesiones falsificables en producción** si faltaba `SECRET_KEY` (valor por defecto conocido). Ahora la app
   no arranca en producción sin secretos fuertes.
5. **Panel global inutilizable**: `BILLING_OPERATOR_USER_IDS` nunca se leía del entorno.
6. **Cualquier miembro podía contratar** (checkout con `tenant.read`). Ahora requiere `billing.manage`
   (otorgado a `owner` en registro y por migración a los existentes).
7. **Límites por plan (BILL-02) no integrados**: estaban en `master` pero no en `development`. Integrados
   (desactivados por defecto con `BILLING_ENFORCE_ENTITLEMENTS`).
8. **CI no corría en PR a `development`** (configurado para `develop`). Ramas sin protección.

## 3. Módulos

| Módulo | Estado | Notas |
|---|---|---|
| Autenticación / multiempresa | Completo con pendientes | Login, registro, tenant, permisos, aislamiento probado. Pendiente: **gestión de miembros** (solo listado; sin invitar/cambiar rol/quitar), refresco de sesión |
| Clientes | Completo | Listado, búsqueda, filtros, paginación, alta, edición, detalle, desactivación |
| Eventos | Completo | CRUD, estados, calendario, cliente asociado |
| Inventario | Completo | Categorías, artículos, disponibilidad, reservas idempotentes, movimientos, incidencias, cargos, reportes |
| Cotizaciones | Completo con pendiente | Creación, conceptos, cálculo, estados, PDF. Sin edición de cotización existente |
| Contratos | Completo | Estados, historial, PDF, firma electrónica con OTP, pagos/anticipos, comprobantes |
| Logística | Parcial | Órdenes, preparación, despacho, entrega. La devolución se gestiona en operaciones de inventario, no como estado de la orden |
| Suscripciones Mercado Pago | Completo en código, **sin validar en vivo** | Ver `MERCADOPAGO.md`; falta prueba E2E con credenciales |
| Panel global | Completo | Precios versionados con auditoría, activar/desactivar, suscripciones, pagos, auditoría, incidencias |

Porcentaje estimado de avance hacia el lanzamiento: **~80 %** (criterio: proporción de criterios de
aceptación del lanzamiento cumplidos y verificados con evidencia; es una estimación, no una medición).

## 4. Cambios realizados (resumen)

Backend: verificación del cobro en conciliación; cobros rechazados auditados/`past_due`; estado `paused`;
cancelación confirmada por el proveedor; consulta de último checkout; permiso `billing.manage`; registro de
incidencias de conciliación; panel global (historial, auditoría, activar/desactivar, suscripciones, pagos);
validación estricta de importes; validación de configuración de producción; cabeceras de seguridad; rate
limiting en login/registro; `ProxyFix` configurable; validación de slug/correo en registro; `wsgi.py`,
`gunicorn.conf.py`, Dockerfile de producción; requirements mínimos (se retiraron PyAutoGUI, Selenium,
pywhatkit, etc., no usados por la app) + `cryptography` (necesario para MySQL 8); siembra de catálogo en
producción con confirmación; resiembra compatible con precios versionados; CI en `development`.

Frontend: árbol de rutas reparado y lazy-loading total; páginas de planes, suscripción (uso + cancelación),
retorno (consulta al servidor, ignora parámetros de URL), panel global de precios y suscripciones;
`operatorGuard`; aviso global de límite de plan; nginx de producción con CSP/HSTS; caché `.angular` fuera de Git.

## 5. Backlog priorizado para el lanzamiento

| # | Tarea | Responsable | Depende de | Estimación |
|---|---|---|---|---|
| 1 | Rotar todas las credenciales expuestas | Tú | — | 1–2 h |
| 2 | Revisar y autorizar commit/push/PR de `release/v1.0-hardening` | Tú | — | 1 h |
| 3 | Decidir política de prueba gratuita y activación de límites | Tú (negocio) | — | — |
| 4 | Elegir y aprobar infraestructura (dominio, MySQL administrado, Redis, VM) | Tú | — | — |
| 5 | Desplegar staging y aplicar migraciones | Dev | 2, 4 | 4–6 h |
| 6 | Prueba E2E de Mercado Pago en staging | Dev + tú (credenciales) | 1, 5 | 3–4 h |
| 7 | Backups + restauración probada + monitoreo | Dev/DevOps | 4 | 4–6 h |
| 8 | Gestión de miembros (invitar, rol, baja) | Dev | 2 | 10–16 h |
| 9 | Proteger ramas + CI obligatorio | Tú | 2 | 0.5 h |
| 10 | Producción + checklist final | Todos | 1–9 | 4 h |

Ruta crítica: 1 → 2 → 4 → 5 → 6 → 7 → 10. Total pendiente estimado: 30–45 h de trabajo técnico (estimación).

## 6. Riesgos pendientes

- Formato real de `GET /authorized_payments/{id}` no verificado contra la API viva (red bloqueada en el entorno
  de esta entrega). Si no trae `payment.status`, ninguna suscripción se activará (falla cerrada), no habrá
  activaciones indebidas. Verificar en staging.
- La firma de webhook rechaza entregas con más de 5 minutos de antigüedad; si Mercado Pago reutiliza `ts` en
  reintentos, esos reintentos se rechazarán (la conciliación diaria lo cubre).
- La sesión vive solo en memoria (recargar = volver a entrar). Seguro, pero incómodo.
- Política comercial implementada: plan Gratuito sin pago y acceso hasta fin de periodo al cancelar.
- `db check` reporta diferencias de nombres de índices entre modelos y migraciones (cosmético).
- Aviso de compilación CSS "Empty sub-selector" (no bloqueante).

## Estado: **NO LISTO PARA PRODUCCIÓN**

El código compila, las pruebas pasan y los bloqueadores de código conocidos están corregidos, pero faltan
condiciones obligatorias que requieren tu intervención: rotación de secretos, prueba real de Mercado Pago,
infraestructura con HTTPS, backups con restauración probada y monitoreo.
