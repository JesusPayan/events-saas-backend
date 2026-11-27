# Seguridad — Autorización por módulos (MOD-01)

## Principios
1. **El servidor decide.** Ocultar un menú no es control de acceso; `tenant_permission` evalúa
   el módulo en cada petición de escritura.
2. **Aislamiento multi-tenant.** Toda consulta de configuración usa el `tenant_id` resuelto por
   la membresía; los identificadores del cuerpo o la URL nunca seleccionan otra organización
   (probado en `test_tenant_isolation_and_identifier_manipulation`).
3. **Mínimo privilegio.** Configurar giros/módulos exige `members.manage`. Accesos delegados
   (soporte/proveedor) solo leen capacidades. Plantillas y catálogo: `platform.catalog.manage`;
   módulos por plan y banderas: solo el dueño de plataforma.
4. **Sin pérdida de datos.** Desactivar no borra; las lecturas siguen disponibles.
5. **Sin escalamiento comercial.** El giro no otorga módulos fuera del plan; el cliente no puede
   enviar `plan` ni `source`.

## Validaciones de entrada
- Códigos de giro y módulo contra listas cerradas; desconocidos → `400`.
- `custom_description` (solo OTHER) ≤ 255 caracteres; máximo un giro principal.
- Borrador del asistente saneado (`_clean_draft`): solo claves y tipos esperados.
- `business_type` en la red: alfanumérico/guion bajo, ≤ 40.
- `X-Request-ID` saneado antes de registrarse como `correlation_id`.

## Concurrencia
`set_tenant_modules` bloquea la fila de la organización (`SELECT … FOR UPDATE` en MySQL) antes
de leer/escribir; la verificación de operaciones en curso y el cambio ocurren en la misma transacción.

## Auditoría (`audit_events`)
`onboarding.started`, `onboarding.resumed`, `onboarding.completed`, `business_profile.selected`,
`business_profile.updated`, `module.enabled`, `module.disabled`, `module.dependency_resolved`,
`module.disable_rejected`, `module_template.updated`, `module.global_state`,
`plan.entitlements_updated`, `feature_flag.updated`. Cada evento incluye actor, organización y
`correlation_id`.

## Riesgos residuales
- Las lecturas de módulos inactivos siguen permitidas por diseño (historial).
- Desactivar `modules.enforcement` deja la aplicación como antes de v1.3.0 (todo escribible);
  solo el dueño de plataforma puede hacerlo y queda auditado.
- La prueba de concurrencia real (dos transacciones MySQL simultáneas) no se automatizó; el
  bloqueo se revisó por código.
