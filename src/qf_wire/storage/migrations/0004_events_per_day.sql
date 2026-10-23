-- 事件按 (event_id, day) 存储：稳定的 event_id 在不同采集日各保留一行，
-- 避免跨日重复采集把旧日事件迁到新日期，导致历史每日事件与时间线缩水。
CREATE TABLE events_per_day (
    event_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    day TEXT NOT NULL,
    title TEXT NOT NULL,
    sources TEXT NOT NULL DEFAULT '[]',
    source_count INTEGER NOT NULL DEFAULT 1,
    confidence TEXT NOT NULL DEFAULT 'medium',
    first_seen TEXT,
    last_seen TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (event_id, day)
);

INSERT OR IGNORE INTO events_per_day (
    event_id, topic, day, title, sources, source_count, confidence, first_seen, last_seen, updated_at
)
SELECT event_id, topic, day, title, sources, source_count, confidence, first_seen, last_seen, updated_at
FROM events;

DROP TABLE events;

ALTER TABLE events_per_day RENAME TO events;

CREATE INDEX IF NOT EXISTS idx_events_topic_day ON events(topic, day);
