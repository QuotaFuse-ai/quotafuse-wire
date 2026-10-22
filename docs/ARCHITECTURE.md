# 架构说明

## 分层

```text
调用层   CLI(qfw) │ 本地看板 │ MCP Server │ Council(Provider)
          │
核心层   采集调度 → 清洗去重 → 事件聚类 → AI 提炼 → 信源评分 → 结构化输出
          │
数据层   SQLite(wire.db) │ data/archive(按日期) │ data.js(看板兼容)
```

## 模块职责

| 模块 | 职责 |
| --- | --- |
| `qf_wire/core` | `models.py` 数据契约；`scheduler.py` 采集编排；`cleaner.py` 清洗与合规过滤；`deduper.py` 去重；`cluster.py` 事件聚类；`scorer.py` 信源评分 |
| `qf_wire/sources` | `base.py` 适配器抽象；`rss.py` / `html.py` / `api.py` 具体适配器；`registry.py` 注册表；`adapters/` 特殊源 |
| `qf_wire/pipeline` | `fetch.py` 并发采集；`process.py` 清洗→去重→聚类；`digest.py` 提炼；`render.py` 生成 `data.js`；`archive.py` 归档 |
| `qf_wire/storage` | `sqlite.py` / `parquet.py` 持久化与查询；`migrations/` 表结构演进 |
| `qf_wire/provider` | `wire_provider.py` Council DataProvider；`envelope.py` `WireEnvelope` ↔ `DataEnvelope` |
| `qf_wire/mcp` | `server.py` stdio/http 传输；`tools.py` 4 个 MCP 工具 |
| `qf_wire/web` | 本地看板 HTTP 服务与静态资源 |
| `qf_wire/cli` | `qfw` 子命令入口 |
| `qf_wire/config` | `loader.py` 加载；`validator.py` 校验；`migrate.py` 旧配置迁移 |
| `qf_wire/logging` | 统一日志格式，日志只写 stderr |

## 一次 run 的数据流

1. `config.loader` 读取 `topics.yaml` / `sources.yaml` / `digest.yaml` 并校验；
2. `pipeline.fetch` 按赛道并发拉取启用的信源，每源独立超时与重试；
3. `core.cleaner` 清洗 HTML、统一北京时间、过滤合规红线词与过期条目；
4. `core.deduper` 按 URL 与标题指纹去重；
5. `core.cluster` 按标题相似度 + 实体聚类，生成 `event_id` 与时间线；
6. `core.scorer` 计算信源权重（准确率、时效性、重复率）；
7. `pipeline.digest` 按赛道调用用户自己的模型提炼要点；
8. `storage.sqlite` 落库，`archive` 写按日期归档，`render` 生成 `data.js`；
9. stdout 输出结构化摘要；部分源失败时以退出码 8 结束并在看板标注降级。

## 失败模型

- 每个源独立超时（默认 15s）、重试（默认 2 次）与降级标记；
- 单源失败只影响该源：该赛道继续、整体流程不中断；
- 全部源不可用时退出码 4；部分失败退出码 8；
- 查询的对象不存在（如 `qfw event show` 的 event_id）时退出码 6；
- 提炼失败不丢弃已采集数据，可用 `qfw digest --date` 重跑。

## 扩展点

- 新信源：`config/sources.yaml` 增加条目；特殊协议在 `sources/adapters/` 实现并在 `registry.py` 注册；
- 新赛道：`config/topics.yaml` 增加条目，无需改代码；
- 新提炼策略：`config/digest.yaml` 为赛道指定 `prompt_file` 与 `output_schema`；
- 新输出：`WireEnvelope.payload` 扩展字段，保持顶层契约不变。

## M2 实现要点

### 并发采集

- `pipeline.fetch.fetch_many_async()` 在单个事件循环内 `asyncio.gather` 全部信源；
- 全局 `asyncio.Semaphore` 限流，单个 `aiohttp.ClientSession` + `TCPConnector(limit=并发, limit_per_host=4)`；
- 并发度解析顺序：`--max-workers` > `QF_WIRE_FETCH_CONCURRENCY` > 默认 24，统一裁剪到 1..64；
- 每个源独立 `ClientTimeout(total=timeout_sec)`，重试退避 `min(0.2 * attempt, 1.0)` 秒；
- 适配器只实现 `parse(bytes)`，同步 `fetch()` 保留给兼容入口与单源探测。

本地夹具（106 个源、27 个端口、每请求 200ms）实测：

| 并发 | 墙钟 | 相对串行 |
| --- | --- | --- |
| 1（串行基线） | 21.38s | 1.0x |
| 24（默认） | 1.03s | 20.8x |
| 32 | 0.84s | 25.3x |

### 事件聚类

- 标题归一化后取字符 bigram 做余弦相似度，阈值 0.56；
- 64 位 SimHash 作为补充信号（相似度 ≥0.86 且余弦 ≥0.30）；
- 规则实体提取（机构、产品代号、引号短语）：机构集合冲突时禁止合并；
- 事件窗口 7 天，`event_id` 由赛道 + 标题指纹 / 规范 URL 稳定哈希得到，重复运行不变；
- 同一事件 ≥2 个来源时 `confidence=high`，时间线按 `published_at` 升序。

### 信源评分

- 分项：准确率（被多源印证的条目占比，权重 0.5）、时效性（相对同事件首报的时间差，0.3）、独特性（独家条目占比，0.2）；
- 无历史样本时取中性分 0.5，避免冷启动误伤；
- 计数按运行累加并持久化到 `source_scores` 表（迁移 `0002_source_scores.sql`）；
- 综合分 < 0.45 的信源，其单独支撑的要点 `confidence` 降级：`high → medium`，其余 → `low`；
- 看板展示评分与分项，`data.js` 的 `sourceScores` 字段与只读 API 同源。

### 提炼策略

- `digest.yaml` 的赛道条目支持 `prompt_file` / `model` / `output_schema`；
- `TopicDigest` 产出摘要 + 要点 + 条目，`BriefDigest` 只产出摘要 + 要点，条目由本地数据补齐；
- 模型不可用时写入 `status=partial` 的降级结果并保留已采集数据，退出码仍按采集结果判定。


默认仅监听 `127.0.0.1`；无强制 API key；模型调用只发生在使用者指定的本机或用户配置的 API；不引入消息队列、云账户等托管依赖。
