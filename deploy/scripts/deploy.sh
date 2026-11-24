#!/usr/bin/env bash
# Despliega RELEASE_TAG (env/stack.env): backup -> pull -> migraciones -> arranque -> verificación.
# Uso:  scripts/deploy.sh            (usa RELEASE_TAG de env/stack.env)
#       scripts/deploy.sh v1.1.0     (actualiza RELEASE_TAG y despliega)
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -n "${1:-}" ]; then
  sed -i "s/^RELEASE_TAG=.*/RELEASE_TAG=$1/" env/stack.env
fi
set -a; . env/stack.env; set +a
# Primer host de DOMAIN (puede listar varios separados por coma) para la verificación.
PRIMARY_HOST="$(echo "${DOMAIN}" | cut -d, -f1 | tr -d ' ')"
dc() { docker compose --env-file env/stack.env "$@"; }

echo "==> Desplegando ${RELEASE_TAG} en ${PRIMARY_HOST}"
[ "${SKIP_BACKUP:-0}" = 1 ] || scripts/backup.sh
[ "${SKIP_PULL:-0}" = 1 ] || dc pull backend frontend
echo "==> Migraciones (tarea única)"
dc run --rm --no-deps backend python -m flask --app app:create_app db upgrade
dc run --rm --no-deps backend python -m flask --app app:create_app db current
echo "==> Arrancando servicios"
dc up -d --remove-orphans
for _ in $(seq 1 30); do
  if curl -fsS "https://${PRIMARY_HOST}/api/v1/ready" ${CURL_EXTRA:-} >/dev/null; then
    echo "==> OK: https://${PRIMARY_HOST} sirve ${RELEASE_TAG}"; exit 0
  fi
  sleep 4
done
echo "ERROR: la verificación de salud falló. Revisa: docker compose logs backend" >&2
echo "Rollback: scripts/deploy.sh <tag-anterior>  (las migraciones v1 son aditivas)" >&2
exit 1
