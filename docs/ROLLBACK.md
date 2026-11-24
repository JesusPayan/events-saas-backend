# Procedimiento de rollback — EasiAcc Events

Complementa `docs/OPERACION.md` y `deploy/README.md`. Objetivo: volver a la versión anterior en minutos y sin
perder datos.

## Antes de cada despliegue
1. `scripts/deploy.sh` hace un **backup automático** (salvo `SKIP_BACKUP=1`) antes de migrar.
2. Anota la versión vigente: `grep RELEASE_TAG /opt/eventos/deploy/env/stack.env`.

## Rollback de la aplicación (caso normal)
Las migraciones de la serie 1.x son **aditivas**: la versión anterior funciona con el esquema nuevo.

```bash
cd /opt/eventos/deploy && scripts/deploy.sh v1.0.0
```

(Sustituye `v1.0.0` por la versión anterior que estaba en producción). El script vuelve a descargar esas
imágenes, ejecuta `db upgrade` (no hace nada si el esquema ya está al día) y verifica `/api/v1/ready`.

## Rollback de datos (solo si hubo corrupción)
**No ejecutes `flask db downgrade` en producción**: puede borrar tablas nuevas con datos.
1. Pon la aplicación en mantenimiento: `docker compose --env-file env/stack.env stop backend`.
2. Restaura en el panel de Linode la base al punto anterior al incidente (*point-in-time recovery*) en un
   clúster nuevo, o restaura el dump: `gunzip -c <backup>/db.sql.gz | mysql ... <base>`.
3. Si se afectaron archivos: `tar -xzf <backup>/uploads.tar.gz` dentro del volumen `uploads`.
4. Despliega la versión estable con `scripts/deploy.sh <tag>` y verifica.

## Rollback del DNS (cambio de servidor)
Si se migró a otro servidor y falla, vuelve a apuntar los registros `A` de Cloudflare a la IP anterior
(con *DNS only* el cambio se propaga en minutos).

## Después de cualquier rollback
- Revisa `docker compose logs backend` y las incidencias de conciliación en *Plataforma → Suscripciones*.
- Ejecuta `python -m scripts.reconcile_mercadopago --apply` para resincronizar suscripciones.
- Registra causa, hora y versión en el historial del proyecto.
