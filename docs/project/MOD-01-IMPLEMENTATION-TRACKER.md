# MOD-01 — Seguimiento de implementación (v1.3.0)

Rama: `feature/MOD-01-business-type-modules` (backend y frontend). Estado: **listo para revisión, sin commit**.

| Fase | Entregable | Estado |
|---|---|---|
| 1.0 | Auditoría técnica de ambos repositorios | ✔ |
| 1.1 | Modelo de datos y migración aditiva `c08000000001` | ✔ |
| 1.2 | Registro de módulos y `CapabilityService` en servidor | ✔ |
| 1.3 | API de giros, módulos, capacidades y onboarding | ✔ |
| 1.4 | Frontend: asistente, menú dinámico, panel adaptable, configuración, solo lectura | ✔ |
| 1.5 | Administración de plataforma (giros, plantillas, módulos, planes, banderas, adopción) | ✔ |
| 1.6 | Integración con suscripción sin cambios comerciales | ✔ |
| 1.7 | Compatibilidad legado y filtro de red por giro | ✔ |
| 1.8 | Pruebas (backend 429, frontend 23, E2E navegador) y revisión de seguridad | ✔ |
| 1.9 | Documentación y CHANGELOG | ✔ |
| 2.0 | Commit, push y PR | ⏸ Pendiente de autorización |
| 2.1 | Migración en producción y release v1.3.0 | ⏸ Pendiente de autorización |

## Decisiones tomadas sin consulta (no requerían confirmación)
- Submódulos de inventario como capacidades; EXPORTS dentro de REPORTS; AUDIT solo de plataforma.
- Lecturas permitidas en módulos inactivos (historial visible, sin pérdida de datos).
- Restricción por plan opt-in (`plan_modules` vacío = sin restricción) para no cambiar condiciones comerciales.

## Fuera de alcance (no implementado)
CFDI, edición de cotizaciones, imágenes de ofertas, portal del cliente, reservas automáticas entre
organizaciones, comisiones de promotores, pagos entre empresas, 2FA, marketplace, POS, contabilidad, nómina.

## Archivos
Backend: `app/modules_registry.py`, `app/business_profiles_data.py`, `app/models/modules.py`,
`app/services/capability_service.py`, `app/api/modules.py`, migración `c08000000001`, cambios en
`security.py`, `auth.py`, `platform_service.py`, `quote_validation.py`, `catalog_service.py`, `api/catalog.py`;
pruebas `tests/test_mod01_modules.py`, `conftest.py`.
Frontend: `core/capabilities/*`, `pages/onboarding/*`, `pages/settings/business-settings/*`,
`pages/platform/platform-business-types/*`, `pages/platform/platform-modules/*`, rutas, guardas, menú,
panel, layout, catálogo de la red; pruebas `tests/modules.test.mjs`.
