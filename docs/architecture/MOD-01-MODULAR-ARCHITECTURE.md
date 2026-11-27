# MOD-01 — Perfiles de negocio y arquitectura modular (v1.3.0)

## Objetivo
Que cada organización vea y use solo los módulos que necesita según su giro comercial, sin
reescribir el sistema, sin perder datos y sin otorgar acceso pagado por elegir un giro.

## ADR-008 — Registro de módulos en código + configuración por organización en BD

**Contexto.** Las funciones (contratos, pagos, inventario, logística, catálogo, red…) ya existían
como blueprints Flask y rutas Angular. Se necesitaba activarlas/desactivarlas por empresa, con
dependencias y límites por plan, y aplicarlo en el servidor.

**Decisión.**
1. `app/modules_registry.py` es la **fuente de verdad** de módulos, capacidades, dependencias y
   qué blueprint/endpoint pertenece a cada módulo. Se valida al importar (sin ciclos ni
   dependencias desconocidas).
2. La BD guarda lo editable: catálogo de giros, plantillas giro→módulos, interruptor global por
   módulo, módulos por plan, banderas de activación y la configuración de cada organización.
3. `app/services/capability_service.py` es el **único** punto de decisión. `tenant_permission`
   lo consulta en cada petición; el frontend solo lo refleja.
4. Lecturas siempre permitidas; escrituras requieren el módulo activo. Desactivar nunca borra.

**Alternativas descartadas.** Módulos solo en BD (riesgo de desincronía con el código y ciclos
editables en caliente); ocultar en el frontend (no es seguridad); microservicios por módulo
(cambio de arquitectura mayor, fuera de alcance).

**Consecuencias.** Agregar un módulo nuevo = entrada en el registro + migración de semilla.
Las rutas no mapeadas pertenecen a módulos esenciales y nunca se bloquean.

## Modelo de datos (migración `c08000000001`, aditiva)

| Tabla | Propósito |
|---|---|
| `business_types` | Catálogo de giros (18 + `LEGACY_COMPATIBILITY` interno), versión de plantilla |
| `modules` | Copia administrable del registro; `is_active` = interruptor global |
| `business_type_modules` | Plantilla de módulos recomendados por giro |
| `tenant_business_types` | Giros de la organización; uno principal (`primary_flag` único por tenant) |
| `tenant_modules` | Estado por organización (`enabled`/`disabled`) y origen (`legacy`/`default`/`onboarding`/`manual`) |
| `tenant_onboarding` | Estado del asistente (`pending`/`in_progress`/`completed`/`legacy`), borrador y versiones de plantilla aplicadas |
| `plan_modules` | Módulos incluidos por plan (opcional; sin filas = sin restricción) |
| `feature_flags` | `modules.enforcement` |

## Catálogo de módulos

| Código | Nombre | Tipo | Depende de | Capacidades |
|---|---|---|---|---|
| CORE_DASHBOARD | Panel de control | esencial | — | dashboard.view |
| CORE_CLIENTS | Clientes | esencial | — | clients.manage |
| CORE_EVENTS | Eventos | esencial | — | events.manage |
| CORE_CALENDAR | Calendario | esencial | — | calendar.view |
| COMMERCIAL_QUOTES | Cotizaciones | esencial | — | quotes.manage, quotes.pdf, quotes.pending_prices |
| COMMERCIAL_CONTRACTS | Contratos | opcional | — | contracts.manage, contracts.e_signature |
| COMMERCIAL_PAYMENTS | Pagos y anticipos | opcional | CONTRACTS | payments.manage, payments.receipts |
| COMMERCIAL_CATALOG | Catálogo de servicios | opcional | — | catalog.offers, catalog.availability, catalog.quote_items |
| SUPPLIERS | Proveedores internos | opcional | CATALOG | suppliers.manage, suppliers.portal |
| ORGANIZATION_NETWORK | Red de organizaciones | opcional | CATALOG | network.browse, network.share, network.requests |
| INVENTORY | Inventario | opcional | — | inventory.items, .reservations, .movements, .incidents, .charges, .replenishment, .capacity_alerts |
| LOGISTICS | Logística | opcional | INVENTORY | logistics.orders |
| REPORTS | Reportes | opcional | INVENTORY | reports.inventory, reports.exports |
| TEAM_MANAGEMENT | Equipo | esencial | — | team.manage, team.access_grants |
| SUBSCRIPTION_MANAGEMENT | Suscripción | esencial | — | subscription.manage |
| SPACE_BOOKING | Reservación de espacios | próximamente | — | — |

**Ajustes respecto al documento de requisitos** (para no inventar funciones inexistentes):
- Los «submódulos» de inventario (movimientos, incidencias, cargos, reposición, alertas) son
  **capacidades** de INVENTORY, no módulos separados: comparten tablas y endpoints.
- EXPORTS forma parte de REPORTS; disponibilidad de servicios es capacidad del catálogo.
- AUDIT es exclusivo de plataforma; no se ofrece a organizaciones.
- SPACE_BOOKING se publica como «Próximamente» y no se puede activar.

## Motor de capacidades

`can_access_module(tenant, code, write=...)` devuelve `None` (permitido) o un código de error:

| Estado del módulo | Lectura | Escritura | Código |
|---|---|---|---|
| active | ✔ | ✔ | — |
| disabled | ✔ | ✘ | `module_disabled` |
| plan_locked | ✔ | ✘ | `plan_upgrade_required` |
| dependency_missing | ✔ | ✘ | `module_dependency_required` |
| unavailable (global off / próximamente) | ✔ | ✘ | `module_unavailable` |

Equivalencias con el documento de requisitos: `MODULE_DISABLED`, `PLAN_UPGRADE_REQUIRED`,
`MODULE_DEPENDENCY_REQUIRED`, `MODULE_UNAVAILABLE`, `MODULE_HAS_ACTIVE_OPERATIONS`.

Orden de evaluación en `tenant_permission`: autenticación → membresía o acceso delegado →
organización activa → permiso RBAC → **módulo** (por `request.endpoint`). El resultado se
cachea por petición en `request.environ` y se invalida al cambiar la configuración.

Las cotizaciones (esenciales) validan además cada partida: no se pueden agregar partidas de
inventario, catálogo o red si el módulo correspondiente no está activo.

## Dependencias
- Al activar un módulo se activan automáticamente sus dependencias (`module.dependency_resolved`).
- No se puede desactivar un módulo del que dependen otros activos.
- No se puede desactivar con operaciones en curso (`module_has_active_operations`):
  reservas de inventario de eventos futuros, órdenes logísticas abiertas, contratos en borrador
  o activos, partidas de proveedor/red/catálogo en cotizaciones abiertas.

## Planes y suscripción
- Elegir un giro **solo recomienda**; nunca activa algo fuera del plan.
- `plan_modules` es opcional: un plan sin filas no restringe nada, preservando las condiciones
  comerciales actuales. La restricción solo se aplica con `BILLING_ENFORCE_ENTITLEMENTS=true`.
- Al bajar de plan, los módulos fuera del plan quedan `plan_locked`: datos visibles, sin
  escritura; al volver a subir se reactivan sin intervención. No se borra nada.
- No se modificaron precios, planes, Mercado Pago ni cobros.

## Compatibilidad
Las organizaciones existentes reciben el giro interno `LEGACY_COMPATIBILITY`, onboarding
`legacy` y los 8 módulos opcionales activos: siguen viendo exactamente lo mismo. Pueden abrir el
asistente voluntariamente. Las nuevas inician con onboarding `pending` y los módulos por
omisión (Contratos, Pagos, Catálogo) hasta completar el asistente.

## Frontend
- `AuthService.capabilities` (señal) se carga tras elegir empresa.
- `moduleGuard(code)`: bloquea solo módulos no disponibles; un módulo inactivo o fuera del plan
  se puede consultar en solo lectura (banner en el layout).
- `onboardingGuard` en el panel: lleva al asistente si está `pending`/`in_progress` y el usuario
  puede administrar miembros.
- Menú lateral y widgets del panel dependen de `hasModule()` y permisos.
