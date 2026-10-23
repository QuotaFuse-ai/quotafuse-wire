# 0008 事件按 (event_id, day) 存储

- 状态：已采纳（M2 回归修复）
- 日期：2026-10-23
- 相关：`src/qf_wire/storage/migrations/0004_events_per_day.sql`、`src/qf_wire/storage/sqlite.py`、`src/qf_wire/cli/event.py`、`src/qf_wire/web/server.py`、`tests/integration/test_cross_day_events.py`

## 背景

`event_id` 因为要跨采集保持稳定（时间线、M3 的 `wire_get_timeline` 都依赖它），生成时不包含日期。跨日重复采集同一批条目会得到相同 `event_id`；当 `events` 以 `event_id` 作主键、upsert 又无条件改写 `day` 时，旧日事件行会被迁到新日期，旧日 items 的 `event_id` 随之指向错误日期，历史事件列表与多源统计缩水。

## 决策

1. **事件行以 `(event_id, day)` 为主键**：同一事件在不同采集日各保留一行，重复采集只更新当天的行。
2. **`event_id` 继续不含日期**：它标识“事件本身”，日期是事件在某天的一个投影；这样时间线仍可跨日关联，语义不变。
3. **默认读取取最新一天**：`get_event` / `event_timeline` 在不传日期时 `ORDER BY day DESC LIMIT 1`，既有 CLI、HTTP、MCP 调用方无需改动。
4. **列表按事件去重**：`events_for_topic` 先在 SQL 侧按时间排序，再在 Python 侧按 `event_id` 保留最新一天并截断 `limit`，维持 provider “一个事件一条”的契约。
5. **迁移用表重建**：SQLite 不支持修改主键，0004 以“新表 → 复制 → 删旧表 → 改名”完成升级，`INSERT OR IGNORE` 保证旧数据不丢。

## 理由

- 问题出在存储粒度，而不是聚类算法；按日存行是最小改动，且与 items 的 `(topic, day, url)` 唯一键对齐。
- 保留稳定 `event_id` 让“同一事件跨日演变”依然可查，只是查询必须显式选择日期或默认最新。
- 默认取最新一天让所有存量调用方保持原行为，避免为了修数据语义去改 M3 接口。
- 迁移在 `initialize()` 中自动执行，用户不需要停机或手工脚本。

## 被否方案

| 方案 | 否因 |
| --- | --- |
| `event_id` 加入日期 | 同一事件每天变成新事件，时间线断裂，M3 契约被破坏 |
| 只在渲染时按 day 过滤，不改表 | 旧日事件行已被改写，渲染层拿不到正确的 day，属于治标不治本 |
| upsert 冲突时保留旧 `day` | 新日期的事件行永远不会写入，当天事件列表缺失 |
| 新增 `event_days` 关联表 | 多一层 join 与一致性维护，对当前单机 SQLite 规模是过度设计 |
| 事件表改为不可变，每次插入新行并另存索引 | 实现复杂度高，收益与按日主键相同 |

## 代价与风险

- 同一 `event_id` 在 `events` 中有多行，直接写 SQL 查询的代码必须带 `day` 或接受“最新一天”语义；仓库内调用点已全部更新。
- 回退到旧版本代码时，`event_id` 不再唯一，旧代码可能读到任意一天的重复行；需要回退必须先重建 events 表。
- 长期每天采集会让 `events` 行数随天数线性增长；当前体量（千级/天）无需归档，若未来需要，可按 day 分区或清理。
