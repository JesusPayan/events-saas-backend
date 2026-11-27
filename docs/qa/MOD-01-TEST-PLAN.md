# Plan de pruebas MOD-01

| # | Área | Caso | Automatización |
|---|---|---|---|
| 1 | Alta | Nueva organización inicia con onboarding `pending` y módulos por omisión | `test_new_organization_starts_with_common_modules_and_pending_onboarding` |
| 2 | Giros | Catálogo, giro principal único, OTHER exige descripción, giros internos/desconocidos rechazados | `test_business_type_catalog_and_selection_rules` |
| 3 | Giros | Varios giros = unión de recomendaciones; dependencias resueltas en vista previa | `test_preview_combines_multiple_business_types_and_resolves_dependencies` |
| 4 | Onboarding | Borrador, reanudar, completar idempotente | `test_onboarding_draft_resume_and_idempotent_completion` |
| 5 | Onboarding | Miembro invitado no repite onboarding ni configura | `test_invited_member_does_not_repeat_onboarding_and_cannot_configure` |
| 6 | Registro | Ciclos y dependencias desconocidas rechazados | `test_registry_rejects_circular_and_unknown_dependencies` |
| 7 | Módulos | Auto-activar dependencias, bloquear dependientes, códigos desconocidos, esenciales, próximamente | `test_dependencies_unknown_codes_essentials_and_future_modules` |
| 8 | Desactivación | Bloqueo por reserva activa, historial legible, escritura 403, reactivación | `test_safe_disable_keeps_history_and_reactivation_restores_access` |
| 9 | Planes | Upgrade, downgrade, cancelada, vencida, reactivación; el giro no da acceso pagado | `test_plan_entitlements_upgrade_downgrade_and_no_paid_access_from_business_type` |
| 10 | Planes | Plan sin configuración conserva condiciones actuales | `test_existing_plan_conditions_are_preserved_without_configuration` |
| 11 | Seguridad | Aislamiento entre organizaciones y manipulación de identificadores | `test_tenant_isolation_and_identifier_manipulation` |
| 12 | Plataforma | Plantillas versionadas, interruptor global, límites por rol (admin vs dueño, promotor, miembro) | `test_platform_catalog_templates_and_role_boundaries` |
| 13 | Banderas | `modules.enforcement` apagada desactiva la validación | `test_feature_flag_controls_server_enforcement` |
| 14 | Compatibilidad | Organización anterior conserva todos sus módulos | `test_legacy_organization_keeps_all_previous_modules` |
| 15 | Red | Red respeta módulo desactivado y filtra por giro | `test_network_respects_disabled_module_and_business_type_filter` |
| 16 | Delegado | Acceso delegado lee capacidades, no configura; correlation id en auditoría | `test_delegated_access_reads_capabilities_but_cannot_configure` |
| 17 | Frontend | Rutas con `moduleGuard`, onboarding por empresa, guardas de plataforma, menú, widgets, servidor decide | `tests/modules.test.mjs` (6) |
| 18 | E2E | Registro → asistente → panel → configuración → desactivar → solo lectura | Playwright manual (ver resultados) |
| 19 | Regresión | Suite completa previa (413) | pytest |

Cada prueba del backend cubre varios casos del documento de requisitos (≈40 escenarios en total).
