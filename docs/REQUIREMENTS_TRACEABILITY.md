# 需求追踪矩阵

升级文档 v1.0 的每一条要求 → 落地位置 → 验收方式。测试工程师按本表逐条比对；新增需求时先改本表再改代码。

图例：**M1–M4** 为里程碑阶段；“验收”列写可执行的判定方法。

## 一、定位与边界

| # | 文档要求 | 阶段 | 落地位置 | 验收 |
|---|---|---|---|---|
| R1.1 | 仅做资讯采集与提炼，不输出交易信号/买卖建议 | M1 | `prompts/*.md` 约束、提炼后置检查 | 用交易日语境样例跑提炼，输出中无“买入/卖出/目标价/评级” |
| R1.2 | 数据不出本机，无强制 API key、无托管依赖 | M1 | 默认监听回环、digest 可跳过 | 断网 + 无 key 下 `qfw run --sources-only` 与 `qfw serve` 正常 |
| R1.3 | 保留旧脚本入口，已有部署升级后无需改调用方式 | M1 | `compatibility/*.py` | `python fetch.py` / `digest.py` / `server.py` 均可运行 |
| R1.4 | 与 StockData / Council 职责不重复 | M3 | `docs/PROVIDER_INTEGRATION.md` | 代码中无行情/财报采集实现 |

## 二、分阶段能力

### M1 工程健壮性

| # | 要求 | 落地位置 | 验收 |
|---|---|---|---|
| R2.1 | 模块化重组：core/sources/pipeline/digest/render/cli/mcp/config | `src/qf_wire/*` | 目录与文档目标结构一致，无循环 import |
| R2.2 | 入口同时支持 `python fetch.py` 与 `qfw run` | `compatibility/`、`pyproject.toml` | 两种方式各自跑通 |
| R2.3 | 每源独立超时/重试/降级标记 | `sources/base.py`、`pipeline/fetch.py` | 注入一个必超时源，其余源仍产出，结果标 `degraded` |
| R2.4 | 单源失败不中断全局，看板标注“该源今日不可用” | `pipeline/fetch.py`、`web/` | 看板出现降级标记，进程退出码 8（部分失败） |
| R2.5 | 按日期归档的 SQLite/Parquet | `pipeline/archive.py`、`storage/` | `data/wire.db` 与 `data/archive/<date>` 生成 |
| R2.6 | 历史可查询、增量对比 | `cli/history.py`、`storage/sqlite.py` | `qfw history --topic X --days 7` 返回 7 天数据 |
| R2.7 | 12 赛道 + 100+ 源迁到 `topics.yaml` / `sources.yaml` | `config/` | 12 topics / 106 sources 可加载，schema 校验通过 |
| R2.8 | 用户可增删赛道与 RSS 源，无需改代码 | `config/loader.py`、`cli/topics.py` | 新增一个自定义 topic + 源后 `qfw run --topic 新id` 可跑 |
| R2.9 | 保留 `data.js` 兼容输出 | `pipeline/render.py` | 旧 `index.html` 读取 `window.DATA` 正常渲染 |

### M2 采集与分析深度

| # | 要求 | 落地位置 | 验收 |
|---|---|---|---|
| R3.1 | asyncio + aiohttp 并发采集，100+ 源秒级 | `pipeline/fetch.py` | 全量采集墙钟时间 << 串行基线，并发上限可配 |
| R3.2 | 事件聚类（标题相似度 + 实体提取） | `core/cluster.py` | 同一事件多源报道折叠为一个 event，标“多源 N” |
| R3.3 | 事件时间线 | `core/cluster.py`、`cli/event.py` | `qfw event timeline <id>` 按时间升序输出 |
| R3.4 | 信源质量评分（准确率/时效性/重复率） | `core/scorer.py`、`storage/` | 评分随运行累积，看板可见徽标 |
| R3.5 | 评分参与要点权重 | `pipeline/digest.py` | 低权重源单独报道时 confidence 降级 |
| R3.6 | digest.yaml 按赛道配置 prompt/模型/输出结构 | `config/digest.yaml`、`pipeline/digest.py` | 两个赛道配不同 prompt_file，实际调用不同文件 |

### M3 生态集成

| # | 要求 | 落地位置 | 验收 |
|---|---|---|---|
| R4.1 | WireProvider 注册进 Council DataAccessLayer | `provider/wire_provider.py` | 桩 Council 中 `data_access.get("wire", ...)` 返回数据 |
| R4.2 | 输出带 source/freshness/confidence 溯源字段 | `core/models.py`、`provider/envelope.py` | 信封 12 字段齐全且取值合法 |
| R4.3 | 复用生态 model_gateway | `digest.yaml provider: gateway` | gateway 不可用时降级 claude-cli，再降级为仅采集 |
| R4.4 | 跨项目源清单/赛道/prompt 对齐 | `scripts/export_sources.py` | 导出结构与生态格式一致 |
| R4.5 | MCP 工具 4 个 | `mcp/tools.py` | 客户端 `tools/list` 见 4 个工具，逐个调用成功 |
| R4.6 | 任意 MCP 客户端可消费 | `mcp/server.py` | 真实客户端（Claude Desktop/Cursor）完成一次调用 |

### M4 产品化

| # | 要求 | 落地位置 | 验收 |
|---|---|---|---|
| R5.1 | Docker Compose 一键部署 | `docker-compose.yml`、`Dockerfile`、`docs/DEPLOYMENT.md` | 干净机器 `docker compose up -d` 后 `/api/health` 返回 ok；`./data` 持久化 |
| R5.2 | 只读 API，默认仅本机 | `web/server.py`（`_guard_host` / `_guard_read` / `_guard_write` / `_guard_write_token`） | 非回环 IP 访问被拒；`QF_WIRE_API_TOKEN` + Bearer 后可访问；写接口除 `X-Wire-Request` 外还要求页面写令牌；`Host` 头不匹配 403；`tests/unit/test_web_guard.py`、`tests/integration/test_dashboard_api.py` |
| R5.3 | 多用户配置隔离 | `config/loader.py`（`resolve_user` / `resolve_paths`）、`config/usertoken.py`、`web/server.py`（`_authorize_user`） | 两个 user 目录互不可见；`X-QF-User` 只选择用户，绑定用户实例拒绝切换到他人，共享实例需 `X-QF-User-Token`；`../`、斜杠、超长 id 被拒（400）；`qfw token` 生成/轮换凭据；`tests/unit/config/test_multiuser.py`、`tests/unit/cli/test_token.py` |
| R5.4 | 定时调度（APScheduler 或 cron 模板） | `core/jobs.py`、`cli/schedule.py`、`web/server.py --with-scheduler` | 到点自动 `run` / `digest` / `sources validate`；日志写 stderr 与 `QF_WIRE_LOG_FILE`；`tests/unit/core/test_jobs.py`、`tests/unit/cli/test_schedule.py` |

## 三、CLI 契约

| 命令 | 必需行为 | 退出码 |
|---|---|---|
| `qfw run [--topic] [--sources-only]` | 全量/单赛道采集，可选跳过提炼 | 0 / 2 / 3 / 4 / 8 |
| `qfw digest --date` | 指定日期重提炼 | 同上 |
| `qfw serve --port [--with-scheduler]` | 本地看板 + 只读 API；`--with-scheduler` 同时启动定时任务 | 0 / 3 |
| `qfw schedule [--once\|--dry-run]` | 常驻调度 / 立即执行一轮 / 只打印任务表 | 0 / 3 / 8 |
| `qfw sources list\|validate` | 列出/探测源 | 0 / 4 |
| `qfw topics list\|add --file` | 赛道管理 | 0 / 2 / 3 |
| `qfw history --topic --days` | 历史查询 | 0 / 2 |
| `qfw token --user [--rotate]` | 生成/轮换多用户 API 凭据 | 0 / 2 |
| `qfw event show\|timeline` | 事件查看 | 0 / 2 / 6（不存在） |
| `qfw mcp stdio\|http --port` | MCP 服务 | 0 / 3 |
| `qfw config validate\|migrate` | 配置校验/迁移 | 0 / 3 |

全局：`--output json|table|csv`；结果走 stdout、日志走 stderr；`qfw mcp stdio` 的 stdout 只有协议报文。

## 四、配置契约

| 文件 | 必需字段 | 校验 |
|---|---|---|
| `topics.yaml` | `id/name/keywords/sources`，可选 `accent/legacy_key/aliases` | JSON Schema + 引用完整性（sources 必须存在） |
| `sources.yaml` | `id/name/type/url`，可选 `timeout_sec/retries/weight/enabled` | type ∈ rss/html/api；url 为 http(s) |
| `digest.yaml` | `provider/default_model/output_schema` | provider ∈ claude-cli/api/gateway |
| `schedule.yaml` | `enabled/timezone/jobs[]` | cron 表达式合法 |

旧配置：首次启动检测并迁移，旧文件保留只读。

## 五、数据契约

`WireEnvelope` 12 字段：`domain, topic, event_id, data_as_of, payload, source, source_detail, fetched_at, freshness, confidence, source_status`。

- `freshness` ∈ realtime/cached/archive
- `confidence` ∈ high/medium/low
- `source_status` ∈ ok/degraded/partial
- `contract/test_wire_envelope.py` 覆盖字段缺失、枚举越界、序列化往返。

## 六、测试与安全验收

| 类型 | 覆盖 | 位置 |
|---|---|---|
| 采集测试 | 正常/超时/空数据/格式变化 | `tests/unit/sources/`、`tests/integration/test_fetch_all.py` |
| 并发测试 | 106 源耗时与稳定性 | `tests/integration/test_fetch_all.py` |
| 聚类测试 | 多源聚合准确性 | `tests/integration/test_cluster.py` |
| 评分测试 | 权重计算与展示 | `tests/unit/core/` |
| 配置测试 | 三份 YAML schema | `tests/unit/` |
| MCP 测试 | stdio/http 联调 | `tests/contract/test_mcp_tools.py` |
| 兼容测试 | 旧入口与迁移 | `tests/compat/` |
| 安全测试 | 仅本机监听/API 鉴权/脱敏/路径穿越 | 安全工程师独立复核 |

## 七、上线前核验

1. PyPI 上 `quota-fuse-wire` / `qf-wire` / `qfw` 名称可用性；
2. 旧仓库名与旧入口过渡期时长（建议 ≥ 两个 minor 版本）；
3. 端口 8790 / 8791 与 8787 / 8788 / 8793 无冲突；
4. 默认回环监听、只读 API 鉴权、敏感配置脱敏；
5. 真实 MCP 客户端完成 `qfw mcp stdio` 联调；
6. 干净环境 `pip install quota-fuse-wire` + 旧配置迁移；
7. 与 Council 联调 WireProvider，`DataEnvelope` 字段对齐。

## 八、明确不做

| 项 | 原因 |
|---|---|
| Kafka 等重型消息队列 | 规模不需要，违背自包含 |
| 强制托管 / 云端账户 | 破坏数据本机留存卖点 |
| 纯规则抽取替代 LLM 提炼 | 跨源聚合质量下降；数值/实体可用规则辅助 |
| 交易信号 / 买卖建议 | 与全产品线边界冲突 |
