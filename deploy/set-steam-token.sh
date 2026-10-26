#!/bin/sh
# Записывает refresh token Steam (cookie steamRefresh_steam) в .env и перезапускает сборщик.
# Ввод скрыт, чтобы значение не осталось на экране и в истории команд.
# Запуск из папки репозитория: sh deploy/set-steam-token.sh
cd "$(dirname "$0")/.." || exit 1
printf "Вставь значение cookie steamRefresh_steam и нажми Enter: "
stty -echo; read -r T; stty echo; echo
case "$T" in
  *%7C%7C*|*"||"*) ;;
  *) echo "Это не похоже на cookie Steam: в нём должно быть %7C%7C. Ничего не изменено."; exit 1 ;;
esac
sed -i '/^STEAM_REFRESH_TOKEN=/d' .env
echo "STEAM_REFRESH_TOKEN=$T" >> .env
python3 - <<'PY'
import base64, json, time, urllib.parse
v = open(".env").read().split("STEAM_REFRESH_TOKEN=")[1].split()[0]
p = urllib.parse.unquote(v).split("||")[1].split(".")[1]
p += "=" * (-len(p) % 4)
exp = json.loads(base64.urlsafe_b64decode(p))["exp"]
print("Refresh token действует до", time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(exp)))
PY
docker compose up -d --force-recreate collector
sleep 3
docker compose exec -T collector python -m cloud.check_token
