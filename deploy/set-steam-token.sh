#!/bin/sh
# Writes the Steam refresh token (steamRefresh_steam cookie) to .env and restarts the collector.
# Input is hidden so the value does not stay on screen or in shell history.
# Run from the repository folder: sh deploy/set-steam-token.sh
cd "$(dirname "$0")/.." || exit 1
printf "Paste the steamRefresh_steam cookie value and press Enter: "
stty -echo; read -r T; stty echo; echo
case "$T" in
  *%7C%7C*|*"||"*) ;;
  *) echo "This does not look like a Steam cookie: it must contain %7C%7C. Nothing changed."; exit 1 ;;
esac
sed -i '/^STEAM_REFRESH_TOKEN=/d' .env
echo "STEAM_REFRESH_TOKEN=$T" >> .env
python3 - <<'PY'
import base64, json, time, urllib.parse
v = open(".env").read().split("STEAM_REFRESH_TOKEN=")[1].split()[0]
p = urllib.parse.unquote(v).split("||")[1].split(".")[1]
p += "=" * (-len(p) % 4)
exp = json.loads(base64.urlsafe_b64decode(p))["exp"]
print("Refresh token valid until", time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(exp)))
PY
docker compose up -d --force-recreate collector
sleep 3
docker compose exec -T collector python -m cloud.check_token
