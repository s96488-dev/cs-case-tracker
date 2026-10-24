import os

# Подключение к локальному PostgreSQL.
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/cs_prices")
# Адрес облачного сборщика и его токен.
CLOUD_URL = os.getenv("CLOUD_URL", "http://localhost:8000").rstrip("/")
CLOUD_TOKEN = os.getenv("CLOUD_TOKEN", "")
# Как часто забирать новые данные из облака, секунды.
SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL", "60"))
SYNC_BATCH = int(os.getenv("SYNC_BATCH", "5000"))
API_PORT = int(os.getenv("API_PORT", "8080"))
