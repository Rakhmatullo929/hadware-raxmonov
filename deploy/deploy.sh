#!/usr/bin/env sh
set -e
cd "$(dirname "$0")/.."

export COMPOSE_PROJECT_NAME=rental_track
COMPOSE="docker compose -f docker-compose.prod.yml"

mkdir -p deploy/nginx/conf.d

# Pick nginx config by whether a real certificate exists (checked via certbot's
# mounted volume, so we never have to guess the docker volume name).
if $COMPOSE run --rm --no-deps --entrypoint sh certbot \
     -c 'test -f /etc/letsencrypt/live/rakhmonov-arenda.uz/fullchain.pem' >/dev/null 2>&1; then
  echo "[deploy] certificate present -> SSL nginx config"
  cp deploy/nginx/templates/app.ssl.conf deploy/nginx/conf.d/default.conf
else
  echo "[deploy] no certificate yet -> bootstrap HTTP nginx config"
  cp deploy/nginx/templates/app.http.conf deploy/nginx/conf.d/default.conf
fi

echo "[deploy] build & up..."
$COMPOSE up -d --build

# Reload nginx so it picks up a swapped default.conf without a full recreate.
$COMPOSE exec -T nginx nginx -s reload >/dev/null 2>&1 || true

$COMPOSE ps
echo "[deploy] done."
