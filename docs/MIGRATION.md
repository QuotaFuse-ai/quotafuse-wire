# 早期版本配置迁移

Wire 保证两个承诺：**旧入口仍能跑**、**旧数据仍能看**。迁移是自动的，不要求用户先手工改配置。

- [兼容面](#兼容面)
- [自动迁移](#自动迁移)
- [旧入口行为](#旧入口行为)
- [数据格式兼容](#数据格式兼容)
- [过渡期与下线条件](#过渡期与下线条件)

## 兼容面

| 旧资产 | Wire 里的位置 | 状态 |
|---|---|---|
| `fetch.py` | `compatibility/fetch.py` → `qfw run --sources-only` | 保留 |
| `digest.py` | `compatibility/digest.py` → `qfw digest` | 保留 |
| `server.py` | `compatibility/server.py` → `qfw serve` | 保留 |
| `index.html` | `compatibility/index.html` + `src/qf_wire/web/static/index.html` | 保留 |
| `sources.json` | `config/sources.yaml` + `config/topics.yaml` | 一次性迁移 |
| `llm.config.json` | `config/digest.yaml` | 一次性迁移 |
| `data.js` | `data/data.js`（继续生成，格式不变） | 双向兼容 |
| 12 个行业键（如 `半导体`） | `legacy_key` + `aliases` | 别名长期保留 |

## 自动迁移

首次运行 `qfw` 任一子命令时，检测当前目录（及 `QF_WIRE_DATA_DIR` 的上一级）是否存在旧文件：

```bash
qfw config migrate            # 手动触发，幂等
qfw config migrate --dry-run  # 只打印将要做什么
```

迁移规则：

1. `sources.json` 的 `industries[].key` → `topics.yaml` 的 `legacy_key`，`name` → `name`，`accent` → `accent`。
2. `industries[].sources[]` 的 `hint` 作为源 `id` 的候选，冲突时追加 `_2`；`name` / `type` / `url` 原样保留。
3. 行业 `key` 生成稳定 slug 作为 `topic.id`（中文键无法做目录名和 CLI 参数）。
4. `llm.config.json` 的 `provider`、`baseUrl`、`apiKey`、`model` 映射到 `digest.yaml`；`apiKey` **不落盘明文**，改写为 `api_key_env: QF_WIRE_LLM_API_KEY` 并提示用户设置环境变量。
5. 旧文件迁移后**保留只读**，改名为 `*.migrated.bak` 之外不改内容，Wire 之后不再读取它们。

迁移只发生一次：`config/.migrated` 标记文件存在时跳过；重复执行不覆盖用户已编辑的 YAML。

## 旧入口行为

三个旧脚本是**薄包装**，import 失败时必须给出可执行的修复提示，而不是堆栈：

```
$ python fetch.py
[qfw] 旧入口已升级为 QuotaFuse Wire，正在委托 qfw run --sources-only
提示：pip install -e . 以安装 qfw 命令
```

行为对应：

| 旧用法 | 等价新命令 |
|---|---|
| `python fetch.py` | `qfw run --sources-only` |
| `python digest.py` | `qfw digest` |
| `python server.py` | `qfw serve --port 8793` |
| `python server.py --port 9000` | `qfw serve --port 9000` |

旧看板端口默认 **8793**（沿用旧版默认），新 `qfw serve` 默认 **8790**。两者不冲突，用户可并行对比。

## 数据格式兼容

`data/data.js` 继续按旧格式生成：

```js
window.DATA = { generatedAt, industries: [{ key, name, accent, items: [...] }] }
```

- `key` 写 `legacy_key`（中文或旧英文键），保证旧 `index.html` 不改也能渲染。
- `items[]` 字段保持 `title / url / time / ts / summary / source / zh`。
- 新增字段（`event_id`、`source_count`、`confidence`）只增不改，旧页面忽略未知字段。
- 新看板读同一份 `data.js`，并额外从 SQLite 取事件时间线与信源评分。

结构化查询一律走 SQLite（`data/wire.db`），`data.js` 只是渲染用的投影。

## 过渡期与下线条件

- 过渡期：至少 **两个 minor 版本**，期间旧入口每次运行打印一次弃用提示（stderr），不阻断。
- 下线条件：旧入口调用量统计为零、迁移文档发布满两个版本、看板已完全读 SQLite。
- 下线方式：`compatibility/` 目录整体删除 + 根目录保留一跳转 README；不删除 `legacy_key` 映射，历史数据仍要能按旧键查询。
