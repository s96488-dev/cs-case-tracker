#!/bin/sh
# Одноразовая настройка облачной машины: доступ к Docker без sudo и cron автообновления.
# Запуск из папки репозитория: sh deploy/setup-vm.sh
set -e
cd "$(dirname "$0")/.."
sudo usermod -aG docker "$USER"
LINE="*/5 * * * * $(pwd)/deploy/update.sh >> $(pwd)/update.log 2>&1"
( crontab -l 2>/dev/null | grep -v 'deploy/update.sh' || true; echo "$LINE" ) | crontab -
echo "Готово. Автообновление: $LINE"
echo "Перезайди в SSH, чтобы docker работал без sudo."
