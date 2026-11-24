# Roadmap — EasiAcc Business 2.0 (plataforma multisector)

> Documento de planeación. **No se implementa en la versión 1.x** ni justifica refactorizaciones actuales.

## Visión
Pasar de **EasiAcc Events** (especializada en eventos) a una plataforma modular donde cada empresa activa los
módulos de su giro: EasiAcc Business, POS, Booking, Vet, Rentals, Pay, Analytics y Services.

## Núcleo reutilizable (ya existe en 1.x)

| Capacidad | Código actual | Reutilización |
|---|---|---|
| Identidad, empresas (tenants), sesiones | `app/security.py`, `app/api/auth.py` | Directa |
| Usuarios, roles, permisos, invitaciones | `members_service.py`, `roles` / `role_permissions` | Directa; los roles pasan a depender de los módulos activos |
| Clientes | `clients` | Directa |
| Inventario y movimientos | `inventory_*` | Directa (giros con stock: Rentals, POS) |
| Cotizaciones | `quotes` | Generalizar el vínculo con «evento» a «servicio/proyecto» |
| Contratos y firma electrónica | `contracts`, `contract_signature_*` | Directa |
| Pagos y comprobantes | `contract_payments`, `payment_receipts` | Directa |
| Suscripciones y límites | `billing_*`, `entitlements_service.py` | Base de la activación por módulo |
| Auditoría | `*_audit` | Directa |
| Notificaciones por correo | `email_service.py` | Directa; agregar plantillas por giro |

## Arquitectura propuesta
1. **Núcleo compartido:** identidad, empresas, clientes, documentos, pagos, suscripciones y auditoría.
2. **Módulos especializados** (`events`, `pos`, `booking`, `vet`…), cada uno con sus modelos, rutas y permisos
   (`<modulo>.<accion>`).
3. **Configuración por giro:** al registrarse, la empresa elige su giro, que define los módulos sugeridos, la
   terminología («evento», «cita», «servicio», «orden») y las plantillas de cotización y contrato.
4. **Feature flags y activación por suscripción:** los derechos del plan (`billing_plan_entitlements`) se
   extienden a `module.<nombre>`; el decorador `require_entitlement` ya permite proteger rutas por módulo.
5. **Menús dinámicos:** el frontend construye la barra lateral a partir de módulos activos y permisos.
6. **Campos personalizados:** definiciones por empresa y entidad (JSON validado) para datos propios de cada giro.

## Fases sugeridas
| Fase | Alcance |
|---|---|
| 2.0-a | Módulos y feature flags; terminología configurable; menú dinámico (sin cambiar funcionalidad de eventos) |
| 2.0-b | EasiAcc Rentals (renta de mobiliario sin «evento» obligatorio) |
| 2.0-c | EasiAcc Booking (citas y agenda) y Services (órdenes de servicio) |
| 2.1+ | POS, Vet, Pay (cobros en línea a clientes finales), Analytics |

## Criterios para iniciar
- Lanzamiento 1.x estable en producción y clientes piloto activos.
- Validación con usuarios de al menos un segundo giro (entrevistas o piloto).
- Revisión de costos de infraestructura y del modelo de precios por módulo.
