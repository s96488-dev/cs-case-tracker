import os

# Local PostgreSQL connection.
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/cs_prices")
# Cloud collector URL and its token.
CLOUD_URL = os.getenv("CLOUD_URL", "http://localhost:8000").rstrip("/")
CLOUD_TOKEN = os.getenv("CLOUD_TOKEN", "")
# How often to pull new data from the cloud, seconds.
SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL", "60"))
SYNC_BATCH = int(os.getenv("SYNC_BATCH", "5000"))
# How often to check for new Valve news, seconds.
NEWS_INTERVAL = int(os.getenv("NEWS_INTERVAL", "3600"))
# How often to recompute case EV (when new item prices arrive), seconds.
EV_INTERVAL = int(os.getenv("EV_INTERVAL", "3600"))
API_PORT = int(os.getenv("API_PORT", "8080"))
