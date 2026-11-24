# Operación: backups, restauración, rollback y monitoreo

## Backups

1. **MySQL administrado**: activar backups automáticos diarios + point-in-time recovery, retención ≥ 7 días
   (recomendado 30).
2. **Dump lógico diario adicional** (fuera del proveedor):
   ```bash
   mysqldump --single-transaction --routines --triggers --set-gtid-purged=OFF \
     -h "$DB_HOST" -u "$DB_USER" -p eventos_saas_prod | gzip > eventos_$(date +%F).sql.gz
   ```
   Cifrar y copiar a almacenamiento externo.
3. **Archivos** (`/data/uploads`: contratos PDF y firmas): copia diaria (`rsync`/`rclone`) a bucket con versionado.

## Restauración (probar antes del lanzamiento y luego cada trimestre)

1. Crear una base temporal `eventos_restore_test`.
2. `gunzip -c eventos_AAAA-MM-DD.sql.gz | mysql -h ... eventos_restore_test`
3. Apuntar una instancia de staging a esa base, ejecutar `flask db current` (debe mostrar la cabeza actual)
   y abrir la app: login, listado de clientes, un contrato con su PDF.
4. Registrar fecha, duración y resultado. **El checklist de lanzamiento exige al menos una restauración exitosa.**

## Despliegue y rollback

- Antes de migrar: backup/snapshot de la base.
- Desplegar imágenes etiquetadas (`vX.Y.Z`); nunca `latest`.
- Rollback de aplicación: volver a desplegar el tag anterior.
- Rollback de base: las migraciones de v1 son aditivas, por lo que la versión anterior funciona con el esquema
  nuevo; **no ejecutar `db downgrade` en producción** salvo instrucción explícita (puede borrar tablas nuevas).
  Si hubo corrupción de datos: restaurar desde PITR.

## Monitoreo y alertas (mínimo)

| Qué | Cómo |
|---|---|
| Disponibilidad | Chequeo externo cada minuto a `/api/v1/health` y `/api/v1/ready` (DB) |
| Errores | Logs de gunicorn (stdout) a un agregador; alerta por ritmo de 5xx |
| Webhooks | Panel global > Suscripciones: incidencias sin conciliar; alerta si hay pendientes > 1 h |
| Conciliación | Salida del cron `reconcile_mercadopago` (código 2 = fallos) |
| Recursos | CPU/memoria/disco de la VM y conexiones MySQL |

Los logs no incluyen tokens, cuerpos de webhook ni datos de tarjeta; el log de acceso de gunicorn omite el
query string.
