-- 事件归并依据：记录多条报道为什么被折叠到同一事件（共同实体 / 标题相似度）。
ALTER TABLE events ADD COLUMN explanation TEXT;
