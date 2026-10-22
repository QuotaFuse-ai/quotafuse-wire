-- M2：信源质量评分（增量累计统计）
CREATE TABLE IF NOT EXISTS source_scores (
    source_id TEXT PRIMARY KEY,
    runs INTEGER NOT NULL DEFAULT 0,
    items INTEGER NOT NULL DEFAULT 0,
    corroborated INTEGER NOT NULL DEFAULT 0,
    exclusive INTEGER NOT NULL DEFAULT 0,
    timeliness_sum REAL NOT NULL DEFAULT 0,
    timeliness_samples INTEGER NOT NULL DEFAULT 0,
    accuracy REAL NOT NULL DEFAULT 0.5,
    timeliness REAL NOT NULL DEFAULT 0.5,
    uniqueness REAL NOT NULL DEFAULT 0.5,
    score REAL NOT NULL DEFAULT 0.5,
    updated_at TEXT NOT NULL
);
