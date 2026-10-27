import os
from pathlib import Path

BUFFER_PATH = Path(os.getenv("BUFFER_PATH", "data/buffer.db"))
# Token the home machine uses to pull data. Required.
API_TOKEN = os.getenv("API_TOKEN", "")
STEAM_INTERVAL = int(os.getenv("STEAM_INTERVAL", "60"))
# Rows acknowledged by home are kept this many more hours, just in case.
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "72"))
# If home has not pulled data for longer than this, the oldest rows are dropped after this many days.
MAX_DAYS = int(os.getenv("MAX_DAYS", "60"))
STEAM_PROXY = os.getenv("STEAM_PROXY") or None
# steamLoginSecure cookie of a logged-in Steam account: needed for sales history (pricehistory).
# Empty - sales history is not collected, everything else works.
STEAM_LOGIN_SECURE = os.getenv("STEAM_LOGIN_SECURE", "").strip()
# steamRefresh_steam cookie (domain login.steampowered.com): long-lived; the collector uses it to
# renew the daily steamLoginSecure. If set, STEAM_LOGIN_SECURE can be left empty.
STEAM_REFRESH_TOKEN = os.getenv("STEAM_REFRESH_TOKEN", "").strip()
# How often to refresh sales history (seconds) and the pause between cases within one pass.
HISTORY_INTERVAL = int(os.getenv("HISTORY_INTERVAL", "3600"))
HISTORY_PAUSE = float(os.getenv("HISTORY_PAUSE", "6"))
# Prices of all skins, knives and gloves inside cases (for EV), fetched between case-history passes.
ITEM_PRICES = os.getenv("ITEM_PRICES", "1") == "1"
# Cases to collect contents prices for (comma-separated); empty - all. Cases are processed one by one,
# most liquid first: one case (~250 items) takes roughly 30-60 minutes.
EV_CASES = [c.strip() for c in os.getenv("EV_CASES", "").split(",") if c.strip()]
