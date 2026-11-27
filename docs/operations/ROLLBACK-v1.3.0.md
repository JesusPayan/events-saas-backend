# Rollback v1.3.0 (MOD-01)

## Opción 1 — sin migrar (recomendada)
Desactivar la bandera `modules.enforcement` en Plataforma → Módulos y planes. El servidor deja de
bloquear escrituras por módulo; el menú sigue reflejando la configuración.

## Opción 2 — volver a v1.2.0
1. Desplegar el código v1.2.0 (backend y frontend).
2. `flask db downgrade c07000000001` — elimina **solo** las tablas nuevas de MOD-01
   (giros, módulos, onboarding, módulos por plan, banderas). No toca clientes, eventos,
   cotizaciones, inventario, contratos ni pagos.
3. Se pierde la configuración de giros/módulos hecha después de la migración; los eventos de
   auditoría en `audit_events` se conservan.

Probado en la base de pruebas (downgrade y re-upgrade sin errores).
