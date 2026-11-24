# Estado del proyecto — EasiAcc Events 1.0 (v1.1.0)

Fecha: 2026-11-24 · Rama base: `development` · Versión candidata: **v1.1.0**

**Estado: LISTO PARA STAGING · NO LISTO PARA PRODUCCIÓN.** El código está validado; faltan infraestructura,
configuraciones externas y revisiones legales (ver §4).

## 1. Evidencia de la versión candidata

| Verificación | Resultado |
|---|---|
| Backend `pytest` (MySQL 8.0) | **396 pasan** |
| Migraciones desde base vacía (upgrade → downgrade → upgrade) | OK, cabeza única `b05000000001` |
| `pip check` | Sin conflictos |
| Frontend `npm test` / build de producción | **17 pasan** / compila (inicial ≈ 430 kB) |
| `npm audit --omit=dev` | 0 vulnerabilidades |
| Imagen backend | Corre como `appuser`, sin `.env` dentro, no arranca sin configuración |
| Imagen frontend (nginx) | Configuración válida; landing, favicon y manifiesto incluidos |
| Búsqueda de secretos en archivos versionados | Sin secretos (se retiró `app/dotenv.env`) |
| CI en `development` | Backend y frontend en verde |

## 2. Funcionalidades

Leyenda: **D** desarrollada · **V** validada con pruebas automatizadas y/o navegador · **S** probada en sandbox ·
**P** configurada en producción.

| Módulo | Estado | Notas |
|---|---|---|
| Registro, login, multiempresa | D · V | Aislamiento por empresa con pruebas en todos los módulos |
| Miembros, roles e invitaciones | D · V | Requiere SMTP en producción |
| Sesión persistente y recuperación de contraseña | D · V | Requiere SMTP en producción |
| Clientes, eventos, calendario | D · V | |
| Inventario, reservas, movimientos, incidencias, cargos, reportes, resumen | D · V | |
| Logística (preparación, despacho, entrega) | D · V | La devolución se registra en operaciones de inventario |
| Cotizaciones (PDF) | D · V | Sin edición de cotizaciones existentes |
| Contratos, firma electrónica, pagos y comprobantes | D · V | Comprobantes **no fiscales** (sin CFDI) |
| Suscripciones con Mercado Pago | D · V · **S** | Cobro real en sandbox verificado (2026-11-22). **Webhook pendiente de validar** con URL fija |
| Plan Gratuito y límites por plan | D · V | Activar `BILLING_ENFORCE_ENTITLEMENTS=true` tras sembrar el catálogo |
| Panel global (precios, suscripciones, conciliación) | D · V | |
| Landing comercial `easiacc.com` | D · V | Falta correo de contacto y textos legales finales |
| Despliegue opción A (Linode) | D · V (local) | **P pendiente**: no hay recursos creados |

## 3. Registro de riesgos

| # | Riesgo | Impacto | Probabilidad | Mitigación / estado |
|---|---|---|---|---|
| R1 | Webhook de Mercado Pago no llega en producción | Alto: suscripciones no se activan solas | Media | Validar en staging con URL fija; conciliación diaria (`discover_mercadopago_invoices --apply`) como respaldo |
| R2 | Textos legales no publicados (aviso de privacidad LFPDPPP, términos) | Alto (legal) | Alta si no se atiende | Borradores en frontend `docs/legal/`; revisión de abogado antes de abrir registro público |
| R3 | Marca EasiAcc sin registro ante el IMPI | Medio | Media | Búsqueda en MARCia (clases 9, 35, 42) y solicitud de registro |
| R4 | Correo transaccional sin configurar | Alto: no llegan invitaciones ni recuperaciones | Alta | Contratar Brevo/Resend; registros SPF, DKIM y DMARC en Cloudflare |
| R5 | Historial de Git con secretos antiguos (`.env` de noviembre) | Medio | Baja (credenciales rotadas) | Rotación confirmada por el propietario; reescribir historial es opcional |
| R6 | Restauración de backups no probada en producción | Alto | Media | `scripts/restore-check.sh` semanal; prueba manual antes del lanzamiento |
| R7 | Un solo servidor (opción A) | Medio: caída = indisponibilidad | Baja | Backups del Linode + MySQL administrado con PITR; monitoreo externo |
| R8 | Certificado CA de la base de Linode no verificado contra la app | Medio | Baja | `DB_SSL_CA` tolera certificados sin AKI; `DB_SSL_VERIFY_HOSTNAME=false` si hiciera falta |

## 4. Bloqueadores de producción (requieren al propietario)

1. Crear recursos en Linode (servidor, firewall, MySQL administrado, Object Storage) y DNS en Cloudflare.
2. Credenciales de producción de Mercado Pago y webhook validado.
3. Correo transaccional con dominio verificado.
4. Aviso de privacidad y términos aprobados por un abogado.
5. Backups activos y una restauración probada.
6. Monitoreo externo de `/api/v1/health` y `/api/v1/ready`.
7. Fusionar `development` en `master` y crear el tag `v1.1.0` (el entorno de desarrollo asistido no puede crear tags).

## 5. Pendientes no bloqueantes (siguiente iteración)

- Edición de cotizaciones existentes.
- Devolución como estado propio de las órdenes logísticas.
- Correo de contacto comercial en `BRAND.contactEmail` (activa «Solicitar una demostración»).
- Refinar el logotipo con un diseñador antes de imprimir material o registrarlo.
- Diferencia cosmética de nombres de índices entre modelos y migraciones (`flask db check`).
