#!/bin/sh
# Auto-update of the cloud collector from GitHub. Runs from cron every 5 minutes:
# if origin/main has new commits, pulls them and rebuilds the containers.
# .env and data/ are not in git, so they are left untouched.
cd "$(dirname "$0")/.." || exit 1
git fetch -q origin main || exit 1
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && exit 0
git reset -q --hard origin/main
docker compose up -d --build --remove-orphans
echo "$(date -u '+%F %T') updated to $(git rev-parse --short HEAD): $(git log -1 --format=%s)"
