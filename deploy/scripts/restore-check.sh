#!/usr/bin/env bash
# Prueba de restauración: carga un backup en un MySQL desechable y verifica su contenido.
# No toca la base de producción.  Uso:  scripts/restore-check.sh /var/backups/eventos/<fecha>
set -euo pipefail
src="${1:?ruta del backup}"
( cd "$src" && sha256sum -c SHA256SUMS )
name="eventos-restore-check-$$"
docker run -d --rm --name "$name" -e MYSQL_ROOT_PASSWORD=restorecheck -e MYSQL_DATABASE=restore mysql:8.0 >/dev/null
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
for _ in $(seq 1 60); do docker exec -e MYSQL_PWD=restorecheck "$name" mysqladmin -uroot ping >/dev/null 2>&1 && break; sleep 2; done
sleep 5
start=$(date +%s)
gunzip -c "$src/db.sql.gz" | docker exec -i -e MYSQL_PWD=restorecheck "$name" mysql -uroot restore
q() { docker exec -e MYSQL_PWD=restorecheck "$name" mysql -uroot -N -e "$1" restore; }
echo "alembic_version: $(q 'SELECT version_num FROM alembic_version')"
for t in tenants users clients events contracts tenant_subscriptions billing_mp_payments; do
  echo "$t: $(q "SELECT COUNT(*) FROM $t")"
done
tar -tzf "$src/uploads.tar.gz" | wc -l | xargs echo "archivos en uploads:"
echo "restauración OK en $(( $(date +%s) - start )) s"
