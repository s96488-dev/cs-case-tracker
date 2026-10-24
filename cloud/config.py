import os
from pathlib import Path

BUFFER_PATH = Path(os.getenv("BUFFER_PATH", "data/buffer.db"))
# Токен, по которому домашний компьютер забирает данные. Обязателен.
API_TOKEN = os.getenv("API_TOKEN", "")
STEAM_INTERVAL = int(os.getenv("STEAM_INTERVAL", "60"))
# Подтверждённые домом записи держим ещё столько часов, на всякий случай.
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "72"))
# Если дом не забирал данные дольше, самые старые записи удаляются после стольких дней.
MAX_DAYS = int(os.getenv("MAX_DAYS", "60"))
STEAM_PROXY = os.getenv("STEAM_PROXY") or None
