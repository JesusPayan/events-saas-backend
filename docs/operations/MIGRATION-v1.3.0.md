# Migración v1.3.0 (MOD-01)

## Antes
1. Respaldo completo de la base de datos y prueba de que se puede restaurar.
2. Verificar revisión actual: `flask db current` → `c07000000001`.
3. Ventana de mantenimiento corta (la migración inserta ~10 filas por organización).

## Ejecución
```bash
flask db upgrade            # c07000000001 → c08000000001
```
Crea 8 tablas, siembra 16 módulos, 18 giros + `LEGACY_COMPATIBILITY`, plantillas v1 y la bandera
`modules.enforcement`. Cada organización existente recibe onboarding `legacy`, el giro legado y
los 8 módulos opcionales activos.

## Verificación
```sql
SELECT status, COUNT(*) FROM tenant_onboarding GROUP BY status;        -- todas 'legacy'
SELECT COUNT(*) FROM tenant_modules WHERE state='enabled';             -- 8 × organizaciones
SELECT COUNT(*) FROM business_types;                                   -- 19
```
Probar con un usuario existente: ve el mismo menú que antes y puede crear una cotización.

## Activación gradual
- La bandera `modules.enforcement` inicia activa. Si se detecta un bloqueo inesperado, el dueño de
  plataforma puede desactivarla desde «Módulos y planes» sin desplegar (vuelve al comportamiento previo).
- `plan_modules` inicia vacío: ningún plan restringe módulos hasta que se configure explícitamente.

## Probado
Ejecutado en la base de pruebas (upgrade → downgrade → upgrade: 156 organizaciones → legacy,
1248 filas activas) y en la base de desarrollo. **No ejecutado en producción.**
