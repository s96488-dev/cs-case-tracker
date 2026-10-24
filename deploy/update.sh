#!/bin/sh
# Автообновление облачного сборщика из GitHub. Запускается по cron раз в 5 минут:
# если в origin/main появились новые коммиты — подтягивает их и пересобирает контейнеры.
# .env и data/ в git не входят, поэтому не затрагиваются.
cd "$(dirname "$0")/.." || exit 1
git fetch -q origin main || exit 1
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && exit 0
git reset -q --hard origin/main
docker compose up -d --build --remove-orphans
echo "$(date -u '+%F %T') обновлено до $(git rev-parse --short HEAD): $(git log -1 --format=%s)"
