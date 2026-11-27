# API MOD-01 — Giros, módulos y onboarding

Todas las rutas usan el prefijo `/api` y el encabezado `X-Tenant-ID` cuando aplican a una organización.
Errores: `{"error": "<código>", ...}`.

## Organización (tenant)

| Método | Ruta | Permiso | Descripción |
|---|---|---|---|
| GET | `/business-types` | autenticado | Giros públicos activos con módulos recomendados |
| GET | `/modules` | autenticado | Catálogo de módulos (registro + estado global) |
| GET | `/tenants/current/business-types` | miembro | Giros de la organización |
| PATCH | `/tenants/current/business-types` | `members.manage` | `{items:[{code,is_primary,custom_description?}], apply_recommendations?}` |
| GET | `/tenants/current/modules` | miembro | Estado efectivo por módulo (`status`, `enabled`, `in_plan`, `configurable`) |
| PATCH | `/tenants/current/modules` | `members.manage` | `{modules:{CODE: bool}}` → `{items, result:{enabled,disabled,auto_enabled}}` |
| GET | `/tenants/current/modules/<code>/impact` | miembro | Operaciones en curso y dependientes que impiden desactivar |
| GET | `/tenants/current/capabilities` | miembro o acceso delegado | Módulos efectivos, capacidades y estado de onboarding |
| GET | `/onboarding/status` | miembro | Estado, borrador y `can_manage` |
| PUT | `/onboarding/draft` | `members.manage` | Guarda progreso (`business_types`, `modules`, `step`) |
| POST | `/onboarding/preview` | `members.manage` | Calcula recomendación, dependencias y vista previa del menú |
| POST | `/onboarding/complete` | `members.manage` | Aplica giros y módulos; idempotente (`already_completed`) |

## Plataforma

| Método | Ruta | Permiso |
|---|---|---|
| GET/POST | `/platform/business-types` | `platform.catalog.manage` |
| PATCH | `/platform/business-types/<id>` | `platform.catalog.manage` |
| GET/PUT | `/platform/business-types/<id>/modules` | `platform.catalog.manage` (incrementa `template_version`) |
| GET | `/platform/modules` | `platform.catalog.manage` (uso, planes y banderas) |
| PATCH | `/platform/modules/<code>` | `platform.catalog.manage` (interruptor global; esenciales bloqueados) |
| GET | `/platform/plans` · `/platform/plans/<id>/modules` | `platform.catalog.manage` |
| PUT | `/platform/plans/<id>/modules` | `platform.plans.manage` (solo dueño) |
| PATCH | `/platform/feature-flags/<code>` | `platform.flags.manage` (solo dueño) |
| GET | `/platform/modules/adoption` | `platform.catalog.manage` (solo agregados, sin datos de clientes) |

## Cambios compatibles en endpoints existentes
- `GET /catalog/network?business_type=CODE`: filtro opcional; cada oferta incluye `supplier_business_types`.
  Se excluyen organizaciones con la red desactivada.
- Escrituras en módulos inactivos responden `403 {"error":"module_disabled","module":"INVENTORY"}`
  (o `plan_upgrade_required`, `module_dependency_required`, `module_unavailable`).
- Partidas de cotización de un módulo inactivo: `403 {"errors":{"items[i]":"module_disabled"},"module":...}`.
- Desactivar con operaciones en curso: `409 {"error":"module_has_active_operations","operations":[...]}`.

No se eliminó ni renombró ningún campo o ruta existente.
