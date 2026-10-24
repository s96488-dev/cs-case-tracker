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

-- Курсор синхронизации: id последней записи облачного буфера, сохранённой здесь.
CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value BIGINT NOT NULL
);
