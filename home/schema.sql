-- Схема домашней базы PostgreSQL. Применяется автоматически при запуске синхронизатора.
CREATE TABLE IF NOT EXISTS items (
    id               SERIAL PRIMARY KEY,
    market_hash_name TEXT NOT NULL UNIQUE,
    item_type        TEXT NOT NULL,              -- case | skin | ...
    icon_url         TEXT,
    attributes       JSONB NOT NULL DEFAULT '{}', -- параметры скинов (износ, float, StatTrak...) в будущем
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS price_ticks (
    item_id     INTEGER     NOT NULL REFERENCES items(id),
    source      TEXT        NOT NULL DEFAULT 'steam',
    ts          TIMESTAMPTZ NOT NULL,
    price_cents INTEGER     NOT NULL,
    currency    TEXT        NOT NULL DEFAULT 'USD',
    listings    INTEGER,
    PRIMARY KEY (item_id, source, ts)
);

-- История продаж Steam (pricehistory): число продаж за час (раньше ~30 дней — за день) и медианная
-- цена в центах USD. median_cents пустой, если Steam отдал историю не в долларах (валюта аккаунта).
CREATE TABLE IF NOT EXISTS sales_history (
    item_id      INTEGER     NOT NULL REFERENCES items(id),
    source       TEXT        NOT NULL DEFAULT 'steam',
    ts           TIMESTAMPTZ NOT NULL,
    median_cents INTEGER,
    volume       INTEGER     NOT NULL,
    currency     TEXT        NOT NULL,
    PRIMARY KEY (item_id, source, ts)
);
ALTER TABLE sales_history ALTER COLUMN median_cents DROP NOT NULL;
-- Длина периода точки: 3600 (час) или 86400 (день). Старше ~30 дней Steam хранит только дневные точки.
ALTER TABLE sales_history ADD COLUMN IF NOT EXISTS span_secs INTEGER NOT NULL DEFAULT 3600;

-- Курсоры синхронизации: id последних записей облачного буфера (цены и продажи), сохранённых здесь.
CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value BIGINT NOT NULL
);

-- Официальные новости Valve по CS (Steam News API, лента steam_community_announcements).
CREATE TABLE IF NOT EXISTS news (
    gid      TEXT PRIMARY KEY,
    ts       TIMESTAMPTZ NOT NULL,
    title    TEXT NOT NULL,
    url      TEXT NOT NULL,
    contents TEXT NOT NULL
);

-- Какие кейсы упомянуты в новости (по точному названию кейса в заголовке или тексте).
CREATE TABLE IF NOT EXISTS item_news (
    item_id INTEGER NOT NULL REFERENCES items(id),
    gid     TEXT    NOT NULL REFERENCES news(gid),
    PRIMARY KEY (item_id, gid)
);
