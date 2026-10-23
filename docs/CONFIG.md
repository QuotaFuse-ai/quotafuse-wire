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
      options:
        topics: all
    - id: daily_digest
      cron: "10 7 * * *"
      command: digest
    - id: weekly_source_check
      cron: "0 6 * * 1"
      command: sources validate
      options:
        timeout_sec: 10
```

- `command` 只接受 `run`、`digest`、`sources validate`；
- `cron` 是标准 5 段表达式，`timezone` 无效或 cron 不合法时启动直接报错（退出码 3）；
- `options.topics` 可为 `all`、单个赛道 id 或 id 列表；`run` 支持 `sources_only` / `max_workers`，`sources validate` 支持 `timeout_sec` / `max_workers`；
- 仅在 `enabled: true` 时由内置调度器执行：`qfw serve --with-scheduler` 随看板同进程运行，或 `qfw schedule` 单独运行；`--once` 立即执行一轮，`--dry-run` 只打印任务表。

## 模型配置

两种 provider 任选其一：

- `claude-cli`：调用本机已登录的 Claude Code，零成本；
- `api`：任意 OpenAI 兼容接口（DeepSeek / OpenAI / SiliconFlow / OpenRouter 等）。

**推荐在看板里配置**：启动 `qfw serve` 后打开左侧「AI 与生成」，填写接口地址、模型名和 API Key，点「保存配置」即可。保存后点「生成今日要点」（全部赛道或单个赛道），页面会显示逐赛道进度，完成后自动刷新，不需要改任何文件，也不需要另开终端。

页面保存的内容写入 `.env.local`（与 CLI 使用同一套查找规则；设置 `QF_WIRE_ENV_FILE` 可改路径）。这个文件已被 `.gitignore` 忽略，接口只返回密钥掩码，不回显明文。页面写接口只接受本机请求（绑定 127.0.0.1，要求 `X-Wire-Request` 头，并带页面下发的一次性写令牌 `X-QF-Write-Token`），其它网页无法跨站触发。

手动配置（CLI 用户）同样有效：API key 优先从环境变量读取（`QF_WIRE_API_KEY` / `LLM_API_KEY` / `OPENAI_API_KEY`，或 `digest.yaml` 指定变量名），**不要写进仓库**。`digest.yaml` 里的 `provider`、`default_model`、`api_base` 是默认值，页面保存的配置会覆盖它们。

`provider`、模型名、`api_base` 也可以直接用环境变量覆盖：

```bash
QF_WIRE_DIGEST_PROVIDER=api
QF_WIRE_DIGEST_MODEL=deepseek-chat
QF_WIRE_API_BASE=https://api.deepseek.com/v1
QF_WIRE_API_KEY=sk-...
```

## 环境变量与 .env

程序启动时自动读取仓库根目录的 `.env`（再往上找）以及同目录的 `.env.local`，见 `.env.example`。优先级：

```text
真实环境变量 > .env.local > .env > 代码默认值
```

- 仓库里的 `.env` 只放空值，可以提交；
- 填了密钥的覆盖写到 `.env.local`，该文件已被 `.gitignore` 忽略；
- 空值等同于未配置，不会覆盖默认值。

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
