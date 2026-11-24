#!/usr/bin/env bash
# Backup diario: dump lógico de MySQL + archivos subidos (contratos y firmas).
# Uso (cron, como root en el servidor):  /opt/eventos/deploy/scripts/backup.sh
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
set -a; . env/stack.env; set +a

stamp=$(date -u +%Y%m%dT%H%M%SZ)
dest="${BACKUP_DIR:?}/${stamp}"
mkdir -p "$dest"
# Un backup que falla a medias no debe confundirse con uno válido.
completed=0
trap 'rm -f "${cnf:-}"; [ "$completed" = 1 ] || rm -rf "$dest"' EXIT
chmod 700 "${BACKUP_DIR}"

# Credenciales en archivo temporal (no en la línea de comandos ni en el historial).
cnf=$(mktemp)
chmod 600 "$cnf"
printf '[client]\nuser=%s\npassword=%s\nhost=%s\nport=%s\n' \
  "$DB_BACKUP_USER" "$DB_BACKUP_PASSWORD" "$DB_HOST" "${DB_PORT:-3306}" > "$cnf"

# Si existe el certificado CA del proveedor, se verifica el servidor (VERIFY_CA);
# si no, se exige al menos una conexión cifrada (REQUIRED).
ca_file="$(pwd)/env/certs/db-ca.pem"
ca_mount=()
if [ -f "$ca_file" ]; then
  printf 'ssl-mode=VERIFY_CA\nssl-ca=/db-ca.pem\n' >> "$cnf"
  ca_mount=(-v "$ca_file:/db-ca.pem:ro")
else
  printf 'ssl-mode=REQUIRED\n' >> "$cnf"
fi

docker run --rm ${BACKUP_DOCKER_NETWORK:+--network "$BACKUP_DOCKER_NETWORK"} -v "$cnf:/backup.cnf:ro" "${ca_mount[@]}" mysql:8.0 \
  mysqldump --defaults-extra-file=/backup.cnf --single-transaction --quick \
  --routines --triggers --events --set-gtid-purged=OFF --no-tablespaces "$DB_NAME" \
  | gzip -9 > "$dest/db.sql.gz"

# Archivos del volumen de uploads (solo lectura).
docker run --rm -v "${STACK_NAME:-eventos}_uploads:/data/uploads:ro" -v "$dest:/out" alpine:3.20 \
  tar -czf /out/uploads.tar.gz -C /data uploads

chmod 600 "$dest"/*.gz
( cd "$dest" && sha256sum db.sql.gz uploads.tar.gz > SHA256SUMS )
gzip -t "$dest/db.sql.gz"
completed=1
echo "backup ok: $dest ($(du -sh "$dest" | cut -f1))"

if [ -n "${RCLONE_REMOTE:-}" ]; then
  rclone copy "$dest" "${RCLONE_REMOTE}/${stamp}" --immutable
  echo "copiado a ${RCLONE_REMOTE}/${stamp}"
fi

find "${BACKUP_DIR}" -mindepth 1 -maxdepth 1 -type d -mtime +"${BACKUP_RETENTION_DAYS:-14}" -exec rm -rf {} +
