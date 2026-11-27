# Guía de plataforma: giros, módulos y planes

**Giros comerciales** (`platform.catalog.manage`): crear, renombrar, ordenar, activar/desactivar
giros y editar su plantilla de módulos. Cada cambio de plantilla incrementa su versión y queda
auditado; no modifica organizaciones existentes.

**Módulos y planes**:
- Adopción: organizaciones, onboarding completo/pendiente/anteriores a v1.3.0, organizaciones
  por giro y módulos más habilitados (solo agregados).
- Interruptor global por módulo opcional (los esenciales no se pueden apagar). Apagar un módulo
  lo deja en solo lectura para todas las organizaciones.
- Módulos por plan (solo dueño): un plan sin módulos configurados no restringe nada. Solo se
  aplica con la facturación activada. No cambia precios.
- Bandera `modules.enforcement` (solo dueño): interruptor de emergencia de la validación en servidor.

Los roles reservados (Soporte, Finanzas, Auditoría) siguen sin habilitarse.
