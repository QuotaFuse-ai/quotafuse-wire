<h1 align="center">QuotaFuse Wire · 资讯线报</h1>

<p align="center">
  <strong>为 A股投资者打造的全球产业链资讯看板</strong><br>
  12 大赛道 · 100+ 全球信源 · 每日中文「今日要点」 · 数据不出本机
</p>

<p align="center">
  <a href="https://github.com/QuotaFuse-ai/quotafuse-wire"><img alt="version" src="https://img.shields.io/badge/version-0.1.0-blue.svg"></a>
  <a href="https://www.python.org/downloads/"><img alt="python" src="https://img.shields.io/badge/python-3.10%2B-blue.svg"></a>
  <a href="LICENSE"><img alt="license" src="https://img.shields.io/badge/license-MIT-green.svg"></a>
  <a href="config/topics.yaml"><img alt="topics" src="https://img.shields.io/badge/%E8%B5%9B%E9%81%93-12_%E5%A4%A7%E6%96%B9%E5%90%91-orange.svg"></a>
  <a href="config/sources.yaml"><img alt="sources" src="https://img.shields.io/badge/%E4%BF%A1%E6%BA%90-100%2B-red.svg"></a>
  <a href="docs/ARCHITECTURE.md"><img alt="fetch" src="https://img.shields.io/badge/%E9%87%87%E9%9B%86-asyncio_%E5%B9%B6%E5%8F%91-9cf.svg"></a>
  <a href="docs/DEPLOYMENT.md"><img alt="local" src="https://img.shields.io/badge/%E6%95%B0%E6%8D%AE-%E4%B8%8D%E5%87%BA%E6%9C%AC%E6%9C%BA-brightgreen.svg"></a>
  <a href="docs/CONFIG.md"><img alt="llm" src="https://img.shields.io/badge/%E5%A4%A7%E6%A8%A1%E5%9E%8B-%E8%AE%A2%E9%98%85_or_API-purple.svg"></a>
</p>

<hr>

<p align="center">
  <a href="#在-quotafuse-产品线中的位置">产品定位</a> ·
  <a href="#核心能力">核心能力</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#cli">CLI</a> ·
  <a href="#mcp-工具">MCP</a> ·
  <a href="#作为-agent-skill-使用">Agent Skill</a> ·
  <a href="#文档">文档</a>
</p>

<hr>

QuotaFuse Wire 是为 A股投资者打造的全球产业链资讯看板。半导体、AI、机器人、新能源车、航天…… 12 大赛道，对应 A股投资者最关心的板块；而真正驱动板块的领先信号，往往先出现在全球英文信源里。Wire 覆盖 100+ 个公开信源，调用你自己的大模型，把各赛道每日最新动向提炼为中文「今日要点」并完成翻译，统一呈现在一个本地浏览器看板里。

它区别于信息过载的新闻聚合器，核心在于**由 AI 完成阅读与提炼**：每个赛道置顶当日「今日要点」，跨源聚合、同一事件去重，并能下钻到原文核实。采集、存储与看板全部跑在本机（Python + SQLite，无前端构建链），AI 使用你自己的 Claude 订阅（$0）或任意 OpenAI 兼容 API，无需账号、无托管依赖。

**适用场景**

- 跟踪半导体、AI、新能源车、机器人等板块的全球先行信号，但海外资讯多为英文、且分散在上百个信源——Wire 把它们汇成一屏中文要点。
- 同时跟踪多个投资赛道，但资讯庞杂、难以尽读，且多为英文。
- 门户与聚合器提供的是离散信息流；真正需要的是「该赛道当日发生了什么核心进展」——这正是 AI 要点层要解决的问题。

**边界**：Wire 呈现的是行业动向与领先信号，并非行情数据，更不构成投资建议。Industry trends, not financial advice.

## 在 QuotaFuse 产品线中的位置

对使用者来说，Wire 就是上面这个本地资讯看板；对 QuotaFuse 生态来说，它承担「资讯感知层」的角色——把新闻、政策与产业链动态整理成结构化资讯，供 Council 等上层消费。这是它在产品线里的分工，不是面向用户的产品描述。

```text
QuotaFuse StockData   → 数据底座（行情、财报、公告、资金、风险事件）
QuotaFuse Wire        → 资讯感知层（新闻、政策、产业链、多源聚合、AI 提炼）
QuotaFuse Council     → 投研合议层（多角色分析、辩论、回测、告警、报告）
```

职责：Wire 供资讯，StockData 供数据，Council 做决策。三者通过统一的 `DataEnvelope` 与 MCP 工具解耦，不重复建设。

## 核心能力

| 能力 | 说明 |
| --- | --- |
| 模块化内核 | `src/qf_wire/` 分层：core / sources / pipeline / digest / render / cli / mcp / web / provider / storage / config，各层可独立替换与测试 |
| 并发采集 | `asyncio + aiohttp` 并发拉取 100+ 信源；本地 106 源实测 21.4s → 1.0s（并发 24），并发度可用 `QF_WIRE_FETCH_CONCURRENCY` 调整 |
| 单源容错 | 每个信源独立超时、重试与降级标记；任一源失效只降级该源，整轮采集继续 |
| 配置化赛道与信源 | `config/topics.yaml` / `config/sources.yaml` 定义 12 大赛道与 100+ 信源，增删赛道或 RSS 源无需改代码 |
| 按赛道提炼 | `config/digest.yaml` 为每个赛道配置 prompt、模型与输出结构，提炼规则可演进 |
| 结构化输出 | 统一 `WireEnvelope` 契约，附 source / freshness / confidence / source_status 溯源字段；同时生成看板用的 `data.js` |
| 历史归档 | 本地 SQLite + 按日期归档，支持历史回溯与增量对比 |
| 事件聚合 | 标题相似度 + 实体提取聚类，同一事件多源折叠为“多源 N”，并生成事件时间线 |
| 信源质量 | 按准确率、时效性、重复率对信源评分，权重参与要点排序与可信度标注 |
| 本地看板 | `qfw serve` 一键启动，默认仅本机监听 |
| 生态集成 | `WireProvider`（对齐 `DataEnvelope`）+ 4 个 MCP 工具，Council 与任意 MCP 客户端可直接消费 |
| 部署 | 本机 Python 直接运行，或 Docker Compose 一键部署（M4） |

设计原则：**自包含、本地优先、零强制 API key**。代码分层但不引入重型中间件，采集与分析全部在本机完成，数据不出本机。

## 架构

```text
┌─────────────────────────────────────────────────────┐
│ 调用层：CLI(qfw) │ 本地看板 │ MCP Server │ Council  │
└─────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────┐
│ QuotaFuse Wire 核心                                  │
│ 采集调度 │ 清洗去重 │ 事件聚类 │ AI 提炼 │ 信源评分  │
│ 配置化赛道 │ 历史归档 │ 结构化输出                    │
└─────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────┐
│ 数据层                                               │
│ 本地 SQLite / Parquet 归档 │ data.js 兼容输出         │
│ 可选：StockData / 本地文档 / 外部 RSS                 │
└─────────────────────────────────────────────────────┘
```

## 快速开始

要求：Python 3.10+，无需任何托管服务；提炼可选本机 Claude 订阅或任意 OpenAI 兼容 API。

```bash
git clone https://github.com/QuotaFuse-ai/quotafuse-wire.git
cd quota-fuse-wire
python -m pip install -e .

# 全量采集 + 提炼 + 输出
qfw run

# 启动本地看板（默认 http://127.0.0.1:8790）
qfw serve
```

打开看板后，在左侧「AI 与生成」里填写接口地址、模型名和 API Key，保存后点「生成今日要点」即可，不用改配置文件，也不用另开终端。配置只保存在本机 `.env.local`（已被 git 忽略），页面不会回显密钥明文。

喜欢命令行的也可以直接配环境变量或 `config/digest.yaml`，再运行 `qfw digest`，效果相同。

为便于已有部署平滑过渡，根目录保留同名脚本入口，统一委托新内核：

```bash
python fetch.py          # 等价于 qfw run --sources-only
python digest.py         # 对当日数据重新提炼
python server.py         # 启动旧版看板入口（8793）
```

首次启动会自动检测早期版本的配置文件（`llm.config.json`、`sources.json`），迁移到 `config/` 并把旧文件保留为只读。

## CLI

```bash
# 采集与提炼
qfw run                          # 全量采集 + 提炼 + 输出
qfw run --topic semiconductor    # 只跑指定赛道（别名 semi 也可）
qfw run --sources-only           # 只采集不提炼
qfw digest --date 2026-10-22     # 对指定日期数据重新提炼

# 看板
qfw serve --port 8790            # 启动本地看板
qfw serve --with-scheduler       # 看板 + 定时任务同进程

# 定时调度
qfw schedule --dry-run           # 查看 schedule.yaml 的任务表
qfw schedule --once              # 立即执行一轮启用的任务
qfw schedule                     # 常驻调度（Ctrl+C 退出）

# 信源与赛道
qfw sources list
qfw sources validate
qfw topics list
qfw topics add --file topics.yaml

# 历史与事件
qfw history --topic semiconductor --days 7
qfw event show <event_id>
qfw event timeline <event_id>

# MCP
qfw mcp stdio
qfw mcp http --port 8791

# 配置
qfw config validate
qfw config migrate               # 迁移早期版本的配置文件
```

输出约定：

- 结构化结果写 stdout，日志写 stderr；
- 支持 `--output json|table|csv`；
- 退出码：`0` 成功、`2` 参数错误、`3` 配置错误、`4` 源不可用、`6` 对象不存在（如事件 id）、`8` 部分源失败；
- `qfw mcp stdio` 的 stdout 只输出 MCP 协议报文。

## 配置

| 文件 | 用途 |
| --- | --- |
| `config/topics.yaml` | 赛道定义：id、名称、关键词、关联信源、别名 |
| `config/sources.yaml` | 信源清单：id、类型、URL、超时、重试、权重 |
| `config/digest.yaml` | 提炼策略：默认模型、按赛道的 prompt 与输出结构 |
| `config/schedule.yaml` | 定时任务（M4） |

校验命令：`qfw config validate`；JSON Schema 位于 `config/schema/`。

## 数据契约

所有结构化产出统一为 `WireEnvelope`，与 Council 的 `DataEnvelope` 对齐：

```python
class WireEnvelope(BaseModel):
    domain: str          # news / policy / industry
    topic: str
    event_id: str | None
    data_as_of: date
    payload: dict        # 要点、多源列表、时间线
    source: str          # wire
    source_detail: str   # 原始信源列表
    fetched_at: datetime
    freshness: str       # realtime / cached / archive
    confidence: str      # high / medium / low
    source_status: str   # ok / degraded / partial
```

看板消费 `data.js`（`window.DATA`），字段保持旧版结构，仅为新增能力追加字段。

## MCP 工具

| 工具 | 说明 |
| --- | --- |
| `wire_get_digest(topic, date)` | 获取某赛道某日要点 |
| `wire_search_events(keyword, window, topic)` | 查询事件的多源报道 |
| `wire_get_timeline(event_id)` | 获取事件时间线 |
| `wire_list_sources(topic)` | 列出信源与质量评分 |

## 作为 Agent Skill 使用

`skills/quotafuse-wire/` 是一份可直接挂载到支持 Skill 的 Agent 上的技能包，让 Agent 知道**何时取资讯、按什么顺序取、如何标注可信度**，而不是自由发挥。

```text
skills/quotafuse-wire/
├── SKILL.md                    # YAML frontmatter（name / description）+ 操作 SOP
├── references/digest-format.md # WireEnvelope 与日报字段、枚举、最小示例
└── examples/read-daily-brief.md# CLI 与 MCP 两条路径的端到端示例
```

挂载方式按宿主而定，常见两种：

- **目录挂载**：把 `skills/quotafuse-wire/` 复制或软链到宿主的技能目录（如 `~/.claude/skills/`、项目的 `.agent/skills/`），宿主按 `SKILL.md` 的 `description` 决定何时加载。
- **仓库内引用**：Agent 直接读取仓库中的 `skills/quotafuse-wire/SKILL.md`，按其 SOP 调用 MCP 工具或 `qfw` 命令。

无论哪种方式，运行前提都一样：本机已安装 `qfw`、已有归档，并配置 `qfw mcp stdio`（或 `qfw mcp http --port 8791`）。技能只做资讯解释，不输出买卖建议。

## 里程碑

| 里程碑 | 内容 | 验收 |
| --- | --- | --- |
| M1 工程健壮性 | 模块化重组；采集超时/重试/降级；SQLite 归档；配置化赛道与源；旧入口兼容 | 单源失败不拖垮全局；历史可查；旧用法可用 |
| M2 采集与分析深度 | asyncio 并发；事件聚类与时间线；信源评分；可配置提炼策略 | 采集提速；多源聚合可见；评分展示 |
| M3 生态集成 | WireProvider；模型网关复用；MCP 工具；与生态资讯模块对齐 | Council 可消费；MCP 可调用；源列表一致 |
| M4 产品化 | Docker Compose；只读 API；多用户隔离；定时调度 | 一键部署；API 本机监听；多用户隔离 |

## 目录结构

```text
quota-fuse-wire/
├── pyproject.toml
├── README.md
├── config/        # topics / sources / digest / schedule + schema
├── prompts/       # 提炼 Prompt 模板
├── docs/          # 架构、配置、信源、MCP、Provider、迁移、部署
├── src/qf_wire/   # core / sources / pipeline / digest / render / cli / mcp / web / provider / storage / config
├── compatibility/ # 旧版脚本入口兼容层
├── skills/        # Agent Skill：quotafuse-wire
├── data/          # 运行数据（gitignore）
├── tests/         # unit / integration / contract / compat
└── scripts/       # 信源校验、导出、迁移
```

## 文档

- [架构说明](docs/ARCHITECTURE.md)
- [配置规范](docs/CONFIG.md)
- [信源清单与新增指南](docs/SOURCES.md)
- [MCP 工具](docs/MCP_TOOLS.md)
- [与 Council / StockData 集成](docs/PROVIDER_INTEGRATION.md)
- [配置迁移指南](docs/MIGRATION.md)
- [部署](docs/DEPLOYMENT.md)
- [需求追踪矩阵](docs/REQUIREMENTS_TRACEABILITY.md)

## 边界

- 不输出交易信号或买卖建议；
- 不采集、不复刻 StockData 的行情、财报、公告、资金数据；
- 不强制托管、不要求云端账户；
- 默认仅本机监听，敏感配置脱敏。

## License

MIT
