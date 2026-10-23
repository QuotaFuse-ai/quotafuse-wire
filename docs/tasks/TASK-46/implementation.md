# 跨日重复采集导致旧日事件迁移

## 现象

10-22 首次采集后库内 `events` 有 1537 行（day=2026-10-22）。10-23 跨零点再次执行 `qfw run --sources-only` 后，2026-10-22 只剩 184 条事件，1458 条 10-22 的 items 的 `event_id` 指向了 day=2026-10-23 的事件行。

| item.day | event.day | 条数 |
|---|---|---|
| 2026-10-22 | 2026-10-22 | 197 |
| 2026-10-22 | 2026-10-23 | 1458 |
| 2026-10-23 | 2026-10-23 | 1523 |

## 根因

`event_id` 由 `stable_hash("event", topic, title_fingerprint | canonical_url)` 生成，不含日期；同一批条目在次日重新聚类会得到相同 `event_id`。而 `events` 表主键只有 `event_id`，`record_run` 的 upsert 又带 `ON CONFLICT(event_id) DO UPDATE SET day=excluded.day`，于是次日采集直接把旧日事件行改写成当天日期，旧日 items 的 `event_id` 就“悬空”指到了别的日期。

`items` 表在多日采集改造中已改为 `(topic, day, url)` 唯一键，本身没有丢失，问题完全出在 `events` 的存储粒度。

## 修复

1. **事件按 `(event_id, day)` 存储**（迁移 `0004_events_per_day.sql`）：
   - SQLite 不能修改主键，因此建新表 → 复制 → 删除旧表 → 重命名；`INSERT OR IGNORE` 保证旧库升级时行数不丢。
   - 主键改为 `(event_id, day)`，`idx_events_topic_day` 重建。
2. **upsert 不再改写 `day`**：冲突目标改为 `(event_id, day)`，同日重复采集只刷新 title/sources/confidence/时间戳。
3. **按日读取**：
   - `get_event(event_id, day=None)`、`event_timeline(event_id, day=None)` 新增可选日期参数；不传时取 `ORDER BY day DESC LIMIT 1`，保持既有调用方（`qfw event show/timeline`、`/api/event`、`wire_get_timeline`）行为不变。
   - 时间线只取 `items.event_id = ? AND items.day = 事件行 day`，不再跨日混排。
4. **列表保持“一个事件一条”**：`events_for_topic` 仍按 `last_seen/updated_at` 排序，在 Python 侧按 `event_id` 去重保留最新一天后再截断 `limit`，provider / MCP 契约不变。
5. **入口补齐日期参数**：
   - CLI：`qfw event show/timeline` 新增 `--date`，非法日期沿用 `parse_day` 的 400 式错误；指定日期不存在时报“事件不存在: <id>（<date>）”。
   - 看板：`GET /api/event?id=...&date=YYYY-MM-DD`，非法格式返回 400，日期无该事件返回 404；`/api/events` 原本就按 `date` 过滤。

## 兼容性

- **旧库升级**：启动时 `initialize()` 自动执行迁移，无需手工操作；旧 `event_id` 唯一，复制不会产生冲突。
- **旧调用方**：`get_event` / `event_timeline` / provider / MCP 的签名与默认行为不变（默认取最新一天）。
- **数据层语义变化**：`events` 中同一 `event_id` 可有多行，按 `day` 区分；直接写 SQL 查询事件的代码需要带上 `day`（仓库内已全部改完）。

## 测试

新增 7 个用例：

- `tests/unit/storage/test_sqlite.py`
  - `test_cross_day_recollection_keeps_previous_day_events`：两天连续 `record_run`，前一日事件数不变、`get_event`/timeline 按日隔离、`events_for_topic` 去重、history 每日统计稳定、每条旧日 item 都能在当日事件时间线中找到。
  - `test_migration_0004_preserves_existing_events`：在 0001–0003 的库上插入旧事件后升级，事件保留、列序正确、索引存在。
- `tests/unit/cli/test_event.py`
  - `test_event_show_scopes_timeline_by_date`
  - `test_event_timeline_date_selects_day_and_reports_missing`
  - `test_event_list_keeps_previous_day_after_recollection`
- `tests/integration/test_cross_day_events.py`
  - `test_provider_dedupes_event_and_serves_latest_timeline`
  - `test_dashboard_event_api_scopes_by_date`

结果：定向用例 19 passed；全量 `244 passed`（修复前 237）。

端到端复现（真实 CLI + 本地 RSS 服务，相邻两天各跑一次 `qfw run --sources-only --date ...`）：

```
run 2026-10-21: exit=0
run 2026-10-22: exit=0
history: 10-21 items=2 events=2; 10-22 items=2 events=2
day1 events (--date 2026-10-21): count=2   # 次日采集后仍为 2
event show <id> --date 2026-10-21 timeline=1 条 / --date 2026-10-22 timeline=1 条
```

修复前同样的场景会把 10-21 的事件行改写到 10-22，10-21 的事件列表归零。

## 发布与回滚

- 发布：随下个补丁版本自然生效，迁移在首次启动时自动执行。
- 回滚代码而不回滚数据：旧版本按 `event_id` 读取会命中多行中的任意一行（SQLite 未定义顺序），时间线仍可能跨日。若必须回退，需要先用 `event_id` 最新一天的规则重建 `events` 表（旧结构无法表达每日多行）。
- 不涉及配置/CLI 破坏性变更。

## 未做 / 后续

- 未给 `events` 增加 `(topic, day)` 之外的统计缓存；`multi_source` 仍由 provider 侧聚合查询计算。
- M3 联调侧若直接查 SQLite，应使用 `event_id + day` 或当日时间线接口；`wire_get_timeline` 保持默认最新一天的语义。
