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
- 提炼失败不丢弃已采集数据，可用 `qfw digest --date` 重跑。

## 扩展点

- 新信源：`config/sources.yaml` 增加条目；特殊协议在 `sources/adapters/` 实现并在 `registry.py` 注册；
- 新赛道：`config/topics.yaml` 增加条目，无需改代码；
- 新提炼策略：`config/digest.yaml` 为赛道指定 `prompt_file` 与 `output_schema`；
- 新输出：`WireEnvelope.payload` 扩展字段，保持顶层契约不变。

## 本地优先约束

默认仅监听 `127.0.0.1`；无强制 API key；模型调用只发生在使用者指定的本机或用户配置的 API；不引入消息队列、云账户等托管依赖。
