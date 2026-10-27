#!/bin/sh
# One-time cloud VM setup: Docker without sudo and the auto-update cron job.
# Run from the repository folder: sh deploy/setup-vm.sh
set -e
cd "$(dirname "$0")/.."
sudo usermod -aG docker "$USER"
LINE="*/5 * * * * $(pwd)/deploy/update.sh >> $(pwd)/update.log 2>&1"
( crontab -l 2>/dev/null | grep -v 'deploy/update.sh' || true; echo "$LINE" ) | crontab -
echo "Done. Auto-update: $LINE"
echo "Log in to SSH again so docker works without sudo."
