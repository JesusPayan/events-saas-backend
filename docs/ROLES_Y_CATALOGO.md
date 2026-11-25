# Roles con alcance y catálogo de servicios (ROLES-01 + CAT-01)

Migración: `c06000000001` (aditiva, después de `b05000000001`).

## 1. Roles y alcances

| Alcance | Dónde vive | Roles |
|---|---|---|
| Plataforma | `platform_role_assignments` (persona, rol, alcance `platform`, quién lo asignó, fechas) | Dueño de plataforma, Administrador de plataforma, Promotor. Reservados sin permisos: Soporte, Finanzas, Auditoría |
| Organización | `memberships` (una por persona y organización) | Propietario, Administrador, Operativo, Solo lectura y el nuevo **Proveedor** |

Una persona puede tener varias asignaciones de plataforma y varias membresías. Cada operación valida el permiso
**en su alcance**: los endpoints de organización usan `tenant_permission` (usuario + `X-Tenant-ID` + permiso +
organización activa) y los de plataforma `platform_permission`. Un rol de plataforma no abre los datos privados de
ninguna organización.

### Permisos de plataforma

| Permiso | Dueño | Administrador | Promotor |
|---|:-:|:-:|:-:|
| Asignar/retirar administradores (`platform.roles.manage_admins`) | ✓ | | |
| Asignar/retirar promotores (`platform.roles.manage_promoters`) | ✓ | ✓ | |
| Transferir la propiedad (`platform.roles.transfer_owner`) | ✓ | | |
| Precios de planes (`platform.plans.manage`) | ✓ | | |
| Organizaciones: alta y suspensión (`platform.orgs.manage`) | ✓ | ✓ | |
| Suscripciones e incidencias (`platform.billing.operate`) | ✓ | ✓ | |
| Categorías del catálogo (`platform.catalog.manage`) | ✓ | ✓ | |
| Auditoría (`platform.audit.read`) | ✓ | ✓ | |
| Prospectos y referidos propios (`promoter.referrals`) | | | ✓ |

- **Nadie** asigna el rol de dueño desde la pantalla de roles: solo se transfiere. La transferencia otorga el rol al
  nuevo dueño y lo retira al actual en la misma transacción; la plataforma nunca queda sin dueño.
- **Compatibilidad:** los IDs de `BILLING_OPERATOR_USER_IDS` conservan lo que ya podían hacer (precios, suscripciones,
  incidencias y auditoría). Se recomienda migrarlos a roles y vaciar la variable.
- **Primer dueño:** `python -m scripts.grant_platform_owner --email <correo>` (solo si aún no hay dueño).

### Organizaciones

- La plataforma da de alta organizaciones (`POST /platform/organizations`): crea la empresa y envía al propietario una
  invitación con el rol `owner`.
- **Suspensión:** una organización suspendida responde `403 tenant_suspended` en todas sus operaciones.
- **Eliminar organizaciones y transferir la propiedad de una organización** no existían y no se implementaron
  (destructivo / cambia reglas de negocio). Quedan pendientes de definición.

### Acceso a datos privados (delegado)

El administrador de la organización (`members.manage`) concede un acceso **temporal de solo lectura** (1–30 días,
revocable) desde **Miembros y accesos**:

- **Soporte:** solo a personal de plataforma (dueño o administrador).
- **Capacitación:** solo al promotor que refirió a esa organización.

El acceso delegado solo admite permisos de lectura de una lista cerrada (`DELEGATED_READ_PERMISSIONS`) y **cada
consulta** se registra en auditoría (`delegated_access.use`).

### Promotores

- Enlace de referido: `/register?ref=<código>`. Un código inválido no impide el alta.
- Ve sus prospectos y el avance de sus altas (nombre, fecha, estado y plan). No ve clientes, cotizaciones ni
  operaciones de las organizaciones referidas.
- No existe un módulo de comisiones; la pantalla lo indica.

### Auditoría

`audit_events` registra actor, acción, alcance (plataforma u organización), objetivo, detalle, IP y fecha de:
asignación/retiro de roles de plataforma, invitaciones, transferencia de propiedad, alta/suspensión/reactivación de
organizaciones, referidos, accesos delegados (concesión, uso y revocación), invitaciones y cambios de rol o estado de
miembros, y cambios de categorías.

## 2. Catálogo de productos y servicios

- **Categorías globales** (`catalog_categories`) con subcategorías de un nivel, administrables desde el panel de
  plataforma sin publicar versión. Iniciales: las 12 del requerimiento. «Renta de mobiliario» agrupa el inventario y no
  se puede desactivar; «Pirotecnia y espectáculos de efectos especiales» exige revisión de recinto y documentos.
- **Proveedores** (`providers`) por organización. Una oferta sin proveedor es de la propia organización.
- **Ofertas** (`catalog_offers`) por organización: nombre, descripción, categoría, proveedor, estado
  (borrador/publicada/archivada), modalidad de precio (`unit`, `per_person`, `per_hour`, `package`, `per_event`,
  `quote`) y cómo se confirma:
  - `inventory`: consume un artículo de inventario (reglas de inventario existentes).
  - `schedule`: agenda del proveedor con capacidad de eventos por día **local** de la organización; sin capacidad, la
    fecha queda pendiente de confirmación.
  - `manual`: siempre pendiente de confirmación del proveedor.
  - Datos de servicio: duración, invitados mínimo/máximo, cobertura, anticipación mínima, montaje, restricciones del
    recinto y documentos requeridos.
- **Mobiliario existente:** no se migró. Los artículos de inventario aparecen en el catálogo bajo «Renta de
  mobiliario» con sus IDs y precios actuales.
- **Imágenes:** el catálogo actual no admite imágenes, así que las ofertas tampoco (pendiente).

### Cotizaciones mixtas

`quote_items` agrega `offer_id`, `provider_id`, `category_id`, `pricing_mode`, `price_status`, `fulfillment_status`,
`compliance_status` y `service_details`. Las partidas anteriores quedan con precio confirmado y sin confirmación
pendiente, así que sus importes y su flujo no cambian.

- **Bajo cotización:** la partida se guarda con importe 0 y `price_status=pending`; no suma al total («Total
  confirmado») hasta registrar el importe acordado (`PATCH /quotes/{id}/items/{item}`).
- **Aceptar una cotización** se bloquea (`409 pending_items`) mientras haya precios pendientes, fechas sin confirmar o
  documentos sin aprobar. Enviar sí se permite.
- **Proveedores:** un usuario con rol «Proveedor» solo ve y actualiza sus partidas (`/provider/items`): confirma la
  fecha y registra el importe acordado. No puede aprobar la revisión documental ni ver la cotización completa.
- El PDF muestra «Pendiente / Por cotizar» y el «Total confirmado».

## 3. Decisiones reversibles y supuestos

1. **«Varios proveedores» = proveedores registrados por la organización** (subcontratistas), no un marketplace entre
   organizaciones. Hoy el cliente es un registro del CRM, no un usuario; quien arma la solicitud es la organización.
   Un portal para que el cliente final explore y solicite por sí mismo, o un catálogo compartido entre
   organizaciones, cambiaría el modelo de aislamiento y requiere decisión del negocio.
2. Categorías globales administradas por la plataforma; las organizaciones no crean categorías propias.
3. El mapeo de permisos es conservador: `catalog.read` para todos los roles con lectura y `catalog.manage` para
   Propietario, Administrador y Operativo (los mismos que ya administraban inventario).
4. El acceso delegado es solo lectura y de lista cerrada; no incluye exportaciones administrativas ni miembros.

## 4. Dónde se administra

| Qué | Pantalla | Quién |
|---|---|---|
| Roles de plataforma, invitaciones y transferencia | Plataforma → Roles de plataforma (`/platform/roles`) | Dueño (admins y promotores), Administrador (promotores) |
| Organizaciones (alta, suspensión) | Plataforma → Organizaciones (`/platform/organizations`) | Dueño, Administrador |
| Categorías y subcategorías | Plataforma → Categorías del catálogo (`/platform/categories`) | Dueño, Administrador |
| Auditoría | Plataforma → Auditoría (`/platform/audit`) | Dueño, Administrador |
| Prospectos y referidos | Promotor → Mis referidos (`/promoter`) | Promotor |
| Roles internos, invitaciones, rol Proveedor, accesos temporales | Miembros y accesos (`/members`) | Propietario, Administrador |
| Ofertas del catálogo | Catálogo de servicios (`/catalog`) | Propietario, Administrador, Operativo |
| Proveedores | Proveedores (`/providers`) | Propietario, Administrador, Operativo |
| Partidas del proveedor | Proveedor → Mis partidas (`/provider/items`) | Usuario con rol Proveedor |
