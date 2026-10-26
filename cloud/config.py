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
# Cookie steamLoginSecure залогиненного аккаунта Steam: нужен для истории продаж (pricehistory).
# Пусто — история продаж не собирается, остальное работает.
STEAM_LOGIN_SECURE = os.getenv("STEAM_LOGIN_SECURE", "").strip()
# Cookie steamRefresh_steam (домен login.steampowered.com): живёт долго, по нему сборщик сам
# продлевает суточный steamLoginSecure. Если задан, STEAM_LOGIN_SECURE можно не указывать.
STEAM_REFRESH_TOKEN = os.getenv("STEAM_REFRESH_TOKEN", "").strip()
# Как часто обновлять историю продаж (секунды) и пауза между кейсами внутри одного прохода.
HISTORY_INTERVAL = int(os.getenv("HISTORY_INTERVAL", "3600"))
HISTORY_PAUSE = float(os.getenv("HISTORY_PAUSE", "6"))
# Цены всех скинов, ножей и перчаток из кейсов (для EV) в промежутках между проходами истории кейсов.
ITEM_PRICES = os.getenv("ITEM_PRICES", "1") == "1"
# Для каких кейсов собирать цены содержимого (через запятую); пусто — для всех. Кейсы идут по очереди,
# самые ликвидные первыми: один кейс (~250 предметов) собирается примерно за полчаса–час.
EV_CASES = [c.strip() for c in os.getenv("EV_CASES", "").split(",") if c.strip()]
