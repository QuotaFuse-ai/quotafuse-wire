-- 同一 URL 可同时属于多个赛道：唯一键改为 (topic, day, url)，
-- 避免后处理的赛道覆盖前一赛道的 event_id 导致时间线缺失。
DROP INDEX IF EXISTS ux_items_day_url;
CREATE UNIQUE INDEX IF NOT EXISTS ux_items_topic_day_url ON items(topic, day, url);
