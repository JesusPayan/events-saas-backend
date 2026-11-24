# EasiAcc Events 1.0 — Notas de la versión (v1.1.0)

> *Simplifica tu negocio.* Primera versión comercial de EasiAcc Events para negocios de eventos en México.

## Qué es
Una plataforma en línea para administrar **clientes, eventos, inventario, logística, cotizaciones, contratos
con firma electrónica y pagos** desde un solo lugar, con suscripción mensual o anual pagada con Mercado Pago.

## Novedades para los clientes
- **Nueva marca EasiAcc Events** y sitio comercial en `easiacc.com`.
- **Empieza gratis:** plan Gratuito con funciones básicas; contratas un plan cuando necesites más.
- **Trabaja en equipo:** invita a tu equipo con roles (Administrador, Operativo, Solo lectura).
- **Más cómodo:** la sesión se mantiene al recargar la página; recuperación de contraseña por correo.
- **Panel de control** con tus próximos eventos y **resumen de inventario** (entregas, devoluciones y pendientes).
- Fechas y montos en formato de México.

## Para el equipo técnico
- Versión técnica **v1.1.0** (la etiqueta `v1.0.0` ya existe y corresponde a la versión estabilizada previa).
- Migración nueva: `b05000000001` (aditiva). Ejecutar `flask db upgrade` antes de arrancar.
- Sembrar el catálogo y el plan Gratuito:
  `python -m scripts.seed_billing_catalog --allow-production --confirm-database <base>`.
- Variables nuevas: `SESSION_MAX_AGE`, `INVITATION_TTL_DAYS`, `MP_CHECKOUT_PENDING_TTL_MINUTES`, `DB_SSL_CA`,
  `DB_SSL_VERIFY_HOSTNAME`, `TRUSTED_PROXY_COUNT`, y opcionales de marca (`BRAND_NAME`, `PRODUCT_NAME`…).
- `DOMAIN` del stack admite varios hosts: `app.easiacc.com, easiacc.com, www.easiacc.com`.
- Detalle completo: `CHANGELOG.md`. Estado y riesgos: `docs/PROJECT_STATUS.md`.

## Limitaciones conocidas
- Los comprobantes de pago **no son CFDI**.
- No se pueden editar cotizaciones ya creadas.
- El aviso de privacidad y los términos se publican al concluir su revisión legal.
