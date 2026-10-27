-- Home PostgreSQL schema. Applied automatically when the home service starts.
CREATE TABLE IF NOT EXISTS items (
    id               SERIAL PRIMARY KEY,
    market_hash_name TEXT NOT NULL UNIQUE,
    item_type        TEXT NOT NULL,              -- case | skin | ...
    icon_url         TEXT,
    attributes       JSONB NOT NULL DEFAULT '{}', -- skin parameters (wear, float, StatTrak...) in the future
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

-- Steam sales history (pricehistory): units sold per hour (older than ~30 days: per day) and the median
-- price in USD cents. median_cents is empty if Steam returned the history in another currency.
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
-- Point period length: 3600 (hour) or 86400 (day). Steam keeps only daily points older than ~30 days.
ALTER TABLE sales_history ADD COLUMN IF NOT EXISTS span_secs INTEGER NOT NULL DEFAULT 3600;

-- Sync cursors: ids of the latest cloud buffer rows (prices and sales) stored here.
CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value BIGINT NOT NULL
);

-- Official Valve CS news (Steam News API, steam_community_announcements feed).
CREATE TABLE IF NOT EXISTS news (
    gid      TEXT PRIMARY KEY,
    ts       TIMESTAMPTZ NOT NULL,
    title    TEXT NOT NULL,
    url      TEXT NOT NULL,
    contents TEXT NOT NULL
);

-- Cases mentioned in a news item (exact case name in the title or text).
CREATE TABLE IF NOT EXISTS item_news (
    item_id INTEGER NOT NULL REFERENCES items(id),
    gid     TEXT    NOT NULL REFERENCES news(gid),
    PRIMARY KEY (item_id, gid)
);

-- Daily prices of items that drop from cases (skins, knives, gloves): median and volume per day.
CREATE TABLE IF NOT EXISTS item_days (
    market_hash_name TEXT    NOT NULL,
    day              DATE    NOT NULL,
    median_cents     INTEGER NOT NULL,
    volume           INTEGER NOT NULL,
    PRIMARY KEY (market_hash_name, day)
);

-- Case EV per day: sum of "item price over the last 10 sales x drop probability".
-- coverage - probability share of items that have a price on that day (1.0 - fully computed).
CREATE TABLE IF NOT EXISTS case_ev (
    item_id  INTEGER NOT NULL REFERENCES items(id),
    day      DATE    NOT NULL,
    ev_cents INTEGER NOT NULL,
    coverage REAL    NOT NULL,
    PRIMARY KEY (item_id, day)
);
