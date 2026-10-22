-- QuotaFuse Wire M1 初始表结构
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    day TEXT NOT NULL,
    topic TEXT,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    exit_code INTEGER NOT NULL DEFAULT 0,
    source_total INTEGER NOT NULL DEFAULT 0,
    source_ok INTEGER NOT NULL DEFAULT 0,
    source_degraded INTEGER NOT NULL DEFAULT 0,
    source_unavailable INTEGER NOT NULL DEFAULT 0,
    item_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_runs_day ON runs(day);

CREATE TABLE IF NOT EXISTS source_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    day TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    topic TEXT,
    status TEXT NOT NULL,
    error TEXT,
    item_count INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    elapsed_ms INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_source_status_day_source ON source_status(day, source_id);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    topic TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    source_id TEXT,
    sources TEXT NOT NULL DEFAULT '[]',
    summary TEXT NOT NULL DEFAULT '',
    zh TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    event_id TEXT,
    confidence TEXT NOT NULL DEFAULT 'medium',
    fetched_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_items_day_url ON items(day, url);
CREATE INDEX IF NOT EXISTS idx_items_day_topic ON items(day, topic);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    day TEXT NOT NULL,
    title TEXT NOT NULL,
    sources TEXT NOT NULL DEFAULT '[]',
    source_count INTEGER NOT NULL DEFAULT 1,
    confidence TEXT NOT NULL DEFAULT 'medium',
    first_seen TEXT,
    last_seen TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_topic_day ON events(topic, day);

CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    day TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    key_points TEXT NOT NULL DEFAULT '[]',
    items TEXT NOT NULL DEFAULT '[]',
    provider TEXT,
    model TEXT,
    partial INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ok',
    error TEXT,
    fallback INTEGER NOT NULL DEFAULT 0,
    generated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_digests_topic_day ON digests(topic, day);
