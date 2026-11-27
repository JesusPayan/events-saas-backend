# Resultados de pruebas MOD-01 — 2026-11-27

Entorno: contenedor de desarrollo, MySQL 8 local (base de pruebas), Python 3 venv, Node/Angular 20.

| Suite | Antes de MOD-01 | Después | Resultado |
|---|---|---|---|
| Backend `pytest` (completo, API en 127.0.0.1:5001) | 413 passed | **429 passed** (16 nuevas) | ✔ 0 fallos |
| Frontend `npm test` | 17 | **23 pass** (6 nuevas) | ✔ 0 fallos |
| Frontend `ng build` | ✔ | ✔ | Solo la advertencia CSS previa (2 reglas con selector inválido de la librería) |
| Migración `c08000000001` (base de pruebas) | — | upgrade → downgrade → upgrade | ✔ 156 organizaciones → legacy, 1248 módulos activos |
| Migración (base de desarrollo) | — | upgrade | ✔ |

## Verificación en navegador (Playwright, servidores locales)
- Registro de empresa nueva → redirige a `/onboarding`.
- Asistente: Renta de mobiliario + Fotografía; recomendados marcados, esenciales fijos,
  Reservación de espacios «Próximamente»; vista previa del menú; completar → panel.
- Menú: Catálogo, Solicitudes de la red, Contratos, Inventario, Logística, Giros y módulos; sin Proveedores (no recomendado).
- Configuración: desactivar Reportes → `/inventory/reports` muestra banner de solo lectura.
- Organización anterior (luna@demo.test): llega al panel con todos sus módulos y menú sin cambios.
- Plataforma (dueño): «Giros comerciales» y «Módulos y planes» con adopción, catálogo, planes y bandera.
- Sin errores de API ni de JavaScript en consola.

## No ejecutado / limitaciones
- **Concurrencia real** (dos transacciones MySQL simultáneas cambiando módulos): no automatizada; el
  bloqueo `FOR UPDATE` se revisó por código.
- **Producción / staging**: no se migró ni desplegó (requiere autorización).
- **Pruebas de carga** del caché por petición: no ejecutadas.
- **Lectores de pantalla**: se revisaron atributos ARIA (`aria-pressed`, `aria-current`, `role=dialog`),
  sin prueba con lector real.
