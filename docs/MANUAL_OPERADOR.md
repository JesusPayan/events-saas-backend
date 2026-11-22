# Manual del operador global

El panel global administra la parte comercial de Eventos SaaS. **No es un rol de empresa**: el acceso se
concede solo a los IDs de usuario listados en `BILLING_OPERATOR_USER_IDS` del backend. Si la variable está
vacía, el panel queda bloqueado para todos.

## Acceso

1. Inicia sesión y elige cualquier empresa a la que pertenezcas.
2. En el menú lateral aparece la sección **Plataforma** (solo para operadores).

## Precios de planes (`/platform/prices`)

- Cada plan muestra sus precios mensual y anual vigentes y cuántas suscripciones activas tiene.
- **Publicar precio**: escribe el nuevo importe (máx. 2 decimales) y confirma. Se crea una versión nueva
  (v2, v3…) y la anterior se desactiva. Solo afecta a **nuevas** contrataciones.
- **Activar / Desactivar**: activar una versión desactiva la vigente del mismo periodo; desactivar retira el
  periodo del catálogo hasta activar otra versión.
- **Historial**: toda acción queda registrada con fecha, importe anterior/nuevo y usuario.

Importante: las suscripciones existentes conservan el importe con el que se autorizaron en Mercado Pago.
Migrar clientes existentes a una tarifa nueva **no** está implementado: requiere una decisión comercial,
aviso al cliente y un procedimiento específico con Mercado Pago.

## Suscripciones (`/platform/subscriptions`)

- Busca por nombre o identificador de empresa y filtra por estado.
- **Ver detalle**: pagos verificados por Mercado Pago y auditoría de cambios de estado.
- **Notificaciones sin conciliar** (recuadro amarillo): webhooks recibidos que no pudieron vincularse a un
  checkout o cuyo cobro no se pudo verificar. Mercado Pago reintenta automáticamente; si persisten más de una
  hora, revisa el recurso en el panel de Mercado Pago y ejecuta
  `python -m scripts.reconcile_mercadopago --apply`.

## Estados de suscripción

| Estado | Significado |
|---|---|
| Activa | Pago verificado; acceso hasta "Pagado hasta" |
| Pago pendiente (`past_due`) | Falló un cobro de renovación y el periodo pagado terminó |
| Pausada | Pausada en Mercado Pago |
| Cancelada | Cancelación confirmada por Mercado Pago |
