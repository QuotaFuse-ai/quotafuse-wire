# 配置规范

所有配置位于 `config/`，均为可直接编辑的 YAML；启动时校验，不通过时以退出码 3 结束。

## topics.yaml

```yaml
version: 1
topics:
  - id: semiconductor          # 规范 id，小写字母/数字/下划线
    name: 半导体 / 芯片
    accent: "#22d3ee"          # 可选，看板配色
    legacy_key: semi           # 历史数据沿用的赛道键
    aliases: [semi, chip]      # 可选，CLI --topic 可用的别名
    keywords: [芯片, 晶圆, 光刻, 先进制程]
    sources: [digitimes, semianalysis, ee_times]
```

- `id` 全局唯一；`sources` 必须能在 `sources.yaml` 中找到；
- `qfw run --topic semiconductor` 与 `--topic semi` 等价。

## sources.yaml

```yaml
version: 1
defaults:
  timeout_sec: 15
  retries: 2
  weight: 1.0
sources:
  - id: reuters_tech
    name: Reuters Technology
    topic: tech
    type: rss                  # rss | html | api
    url: https://example.com/feed
    timeout_sec: 10
    retries: 2
    weight: 1.0
    enabled: true
```

- `url` 只允许 `http` / `https`；
- `enabled: false` 的源不参与采集，但仍出现在 `qfw sources list` 中；
- `weight` 为人工先验权重，与历史评分共同决定排序。

## digest.yaml

```yaml
digest:
  version: 1
  provider: claude-cli         # claude-cli | api | gateway
  default_model: user-model
  language: zh
  max_items_per_topic: 12
  topics:
    semiconductor:
      prompt_file: prompts/semiconductor.md
      output_schema: TopicDigest
      model: user-model        # 可选，覆盖 default_model
```

未在 `topics` 中出现的赛道使用 `default` 条目。

赛道条目可覆盖的字段：

| 字段 | 说明 |
| --- | --- |
| `prompt_file` | 该赛道使用的提示词文件；相对路径以仓库根目录为基准 |
| `model` | 传给 provider 的模型名；`claude-cli` 会原样转发为 `--model`。`user-model` 是占位符，表示“用 CLI/接口自己的默认模型”，不会转发 |
| `output_schema` | `TopicDigest`（摘要 + 要点 + 条目）或 `BriefDigest`（摘要 + 要点，条目由本地数据补齐） |

## 并发采集

全局并发度由环境变量 `QF_WIRE_FETCH_CONCURRENCY` 控制（默认 24，范围 1..64；`qfw run --max-workers` 可临时覆盖）。
所有请求共享一个 `aiohttp.ClientSession`，单主机最多 `limit_per_host=4` 个连接；单源超时与重试仍由 `sources.yaml` 的 `timeout_sec` / `retries` 决定。

## schedule.yaml

```yaml
schedule:
  version: 1
  enabled: false
  timezone: Asia/Shanghai
  jobs:
    - id: daily_run
      cron: "0 7 * * *"
      command: run
```
仅在 `enabled: true` 时由内置调度器执行。

## 模型配置

两种 provider 任选其一：

- `claude-cli`：调用本机已登录的 Claude Code，零成本；
- `api`：任意 OpenAI 兼容接口（DeepSeek / OpenAI / SiliconFlow / OpenRouter 等）。

API key 优先从环境变量读取（`LLM_API_KEY` 或 `digest.yaml` 指定的变量名），**不要写进仓库**。

## 环境变量

见 `.env.example`。所有变量都有默认值；显式环境变量优先于配置文件中的非敏感项。

## 校验

```bash
qfw config validate            # 校验全部配置
qfw sources validate           # 逐源可用性探测
```

JSON Schema 位于 `config/schema/`，供编辑器与 CI 使用。

## 旧配置迁移

首次启动自动检测仓库根目录的 `llm.config.json` 与 `sources.json`：

- 迁移后旧文件保留且设为只读，不删除；
- `llm.config.json` → `digest.yaml` 的 provider / api 字段；
- `sources.json` → `sources.yaml` 与 `topics.yaml`（按 hint 映射赛道）。

手动执行：`qfw config migrate`。详见 [MIGRATION.md](MIGRATION.md)。
