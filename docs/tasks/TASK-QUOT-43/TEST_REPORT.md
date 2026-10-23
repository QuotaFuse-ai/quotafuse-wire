# QUOT-43 / 全量对比测试报告

- 日期：2026-10-23
- 分支：`agent/QUOT-43-test`（基线 `5551a32`）
- 关联 issue：QUOT-43（父 issue QUOT-39 第 5 阶段）
- 被测版本：`quota-fuse-wire` 0.1.0（`qfw` CLI / `qf_wire`）
- 测试对象：`docs/REQUIREMENTS_TRACEABILITY.md` 全量验收矩阵 R1.1–R5.4 + 第 3 章 CLI 契约
- 产出：本报告 + 3 个测试文件（2 个新增用例文件改动，1 个新增文件），5 条 xfail 复现用例

## 1. 结论摘要

| 指标 | 结果 |
| --- | --- |
| 验收矩阵行数 | 29（R1.1–R1.4 / R2.1–R2.9 / R3.1–R3.6 / R4.1–R4.6 / R5.1–R5.4） |
| 通过 | 25 |
| 部分通过 | 3（R2.7 / R3.3 / R4.2） |
| 不通过 | 0 |
| 无法验证 | 1（R5.1，环境无 Docker） |
| 通过率 | 25/29 ≈ **86.2%**（不含无法验证项为 25/28 ≈ 89.3%） |
| 缺陷 | **P0 1 / P1 4 / P2 6 / P3 4** |
| 自动化回归 | 全量 `231 passed, 5 xfailed`（29.14s）；5 条 xfail 均稳定复现对应缺陷 |

**发布结论：不建议直接进入安全审计。** P0-1（wheel 缺迁移 SQL / prompts / schema）意味着 `pip install` 出来的制品开箱不可用，属于阻断级；必须先修复 P0-1 与 4 条 P1，再进入安全审计，否则审计对象不是可交付的制品。

## 2. 测试环境与方法

- OS：Windows 10.0.19042 x64；Python 3.13（`D:/wk/WorkBuddy/resources/vendor/python/python.exe`）
- 依赖：隔离目录 `%TEMP%/qfw-env`（pytest 9.1.1 等），通过 `PYTHONPATH` 注入，未污染系统环境
- 配置：`QF_WIRE_ROOT` / `QF_WIRE_CONFIG_DIR` / `QF_WIRE_DATA_DIR` 全部指向临时根目录，避免读写用户真实数据
- LLM：`QF_WIRE_CLAUDE_BIN` 指向不存在的可执行文件，用于验证 fallback 与降级路径
- 网络：本地 `ThreadingHTTPServer` 提供 RSS 夹具（`/ok.xml` `/ok2.xml` `/broken.xml` `/bad.xml` `/empty.xml` `/slow.xml` `/flaky.xml` `/multi_a.xml` `/multi_b.xml`）
- 端口：8790（`qfw serve`）/ 8791（`qfw mcp http`）/ 8793（legacy `server.py`）

### 2.1 与官方运行方式的偏差（均已在证据中标注，不计为产品缺陷）

1. **未使用 `pip install .` 安装后调用 `qfw` 入口**：环境不允许改动全局解释器，改用 `python -m qf_wire` + `PYTHONPATH=<repo>/src`。制品安装场景单独用 `pip wheel` + 解包审计覆盖（见 P0-1）。
2. **Docker 不可用**（`docker: command not found`）→ R5.1 无法验证。
3. **未安装 pyarrow** → Parquet 归档走降级分支（`parquet_installed: false`），该降级行为本身被验证为符合预期。
4. **控制台中文乱码**：Windows 控制台 cp936 与 UTF-8 输出的编码差异，属测试环境现象，不是产品缺陷；所有断言均基于重定向到文件的原始字节。
5. **MCP HTTP 客户端在主动终止后进程退出码为 1**：测试夹具的 teardown 行为，协议交互本身全部通过，不计缺陷。

## 3. 逐条验收矩阵

图例：✅ 通过 / ◐ 部分通过 / ✗ 不通过 / ⚠ 无法验证

### R1 合规与定位

| 行 | 结论 | 证据 |
| --- | --- | --- |
| R1.1 投资建议红线 | ✅ | 3 个 prompt 中违禁词命中 0；11 篇 digest 逐篇检查无荐股/买卖表述；MCP `instructions` 含“不构成任何买卖建议” |
| R1.2 本地优先、无云端依赖 | ✅ | 代码中无 API key 常量；`config validate` / `run --sources-only` / `digest` 在无外网凭据下 rc 0（digest 走本地 fallback）；除用户显式配置的模型网关外无外部请求 |
| R1.3 旧入口仍可用 | ✅ | `fetch.py` rc 8（部分失败，符合契约）、`digest.py` rc 0、`server.py` 8793 `/api/health` 200 |
| R1.4 不含行情/交易能力 | ✅ | 全仓无行情数据源代码；`/api/quote` 返回 404 |

### R2 架构与配置

| 行 | 结论 | 证据 |
| --- | --- | --- |
| R2.1 分层架构无循环依赖 | ✅ | 58 模块 / 153 条 import 边 / 0 环；`import_all` rc 0，输出 `57 []` |
| R2.2 配置集中且可校验 | ✅ | `config validate` 对合法配置 rc 0，对非法配置逐条给出中文错误；schema 位于 `config/schema/` |
| R2.3 数据层统一 SQLite + 迁移 | ✅ | 源码树运行建表完整；`schema_migrations` 记录生效；重复运行幂等 |
| R2.4 采集并发与去重 | ✅ | 见 R3.1/R3.2；`ux_items_day_url` 唯一索引生效 |
| R2.5 归档能力 | ✅ | 每日归档 5 个文件；无 parquet 时输出 `parquet_installed: false` 降级说明 |
| R2.6 历史查询与聚合 | ✅ | 7 天历史、topic 过滤、alias 解析均符合契约 |
| R2.7 开箱配置可直接运行 | ◐ | 12 topics / 106 sources 可加载，数量与名称完整；但**仓库自带 `config/digest.yaml` 无法通过自带 schema 校验**（P1-4），`config validate` 在干净根目录 rc 3 |
| R2.8 纯 YAML 增量配置 | ✅ | 仅改 YAML 新增 1 topic + 1 RSS source，`run --topic` rc 0 采到 2 条；schema 非法 / 引用不存在 source / 非法 weight 均 rc 3 且报错清晰 |
| R2.9 前端数据契约 | ✅ | `data.js` 暴露 `window.DATA`；顶层键 `generatedAt, industries, sourceStatus, sourceNotice, sourceScores`；条目键 `title/url/time/ts/summary/source/sources/zh/event_id/source_count/confidence`；`industries[].key` 保留旧键 |

R2.7 判定为部分通过的原因：功能可用，但“开箱即可运行”的前置条件（自带配置能通过自带校验）不成立，见 P1-4。

### R3 采集、事件与聚合

| 行 | 结论 | 证据 |
| --- | --- | --- |
| R3.1 大规模并发采集 | ✅ | 104 fast + 8 slow + 2 broken，并发 16，总耗时 **3.04s**；串行下界 8×1s=8s，实测 < 下界一半；峰值并行度在 2–16 之间且无未关闭 session |
| R3.2 多源事件合并 | ✅ | 同一事件合并为 `6f5eb73ecd960382`，`sources=2`，`confidence=high` |
| R3.3 事件时间线 | ◐ | 单赛道事件时间线正常（升序、条数正确）；**共用信源场景下前一赛道事件时间线为空**（P1-1） |
| R3.4 源评分累积 | ✅ | 连续两轮 run 后 `source_scores` 累积正确 |
| R3.5 置信度分级 | ✅ | 阈值 0.45；仅低权重来源的事件降级为 `medium` |
| R3.6 分赛道 prompt / schema | ✅ | semi 用 `prompts/semiconductor.md` + `TopicDigest`；macro 用 `prompts/policy.md` + `BriefDigest` |

### R4 对外接口

| 行 | 结论 | 证据 |
| --- | --- | --- |
| R4.1 WireProvider 接口 | ✅ | `name: wire`，domains `news/policy/industry`；digest/search/sources/timeline 四类调用均返回合法 envelope；空 topic 返回合法 envelope |
| R4.2 WireEnvelope 字段契约 | ◐ | **实际 11 个字段**，文档第 5 章写“12 字段”（P2-6）；序列化/反序列化往返一致，枚举值全部合法 |
| R4.3 模型网关降级 | ✅ | 网关不可达时自动回退 `claude-cli`，再不可用时输出确定性 fallback digest，均不中断主链路 |
| R4.4 导出能力 | ✅ | 导出 12 topics / 106 sources，结构完整 |
| R4.5 MCP 四工具 | ✅ | `wire_get_digest` / `wire_search_events` / `wire_get_timeline` / `wire_list_sources` 全部可调用 |
| R4.6 传输方式 | ✅ | stdio 与 streamable HTTP（8791 `/mcp`）均为合法 JSON-RPC，协议版本 `2025-11-25` |

R4.2 判为部分通过：字段集合与文档不一致，但实现本身自洽（11 字段往返一致、枚举合法、MCP 输出与之一致）。

### R5 安全与运维

| 行 | 结论 | 证据 |
| --- | --- | --- |
| R5.1 容器化部署 | ⚠ | `docker: command not found`，环境中无 Docker，无法执行 |
| R5.2 本地看板鉴权 | ✅ | 配置 token 后无 token 401 / 带 token 200；非本机会话无 token 403；写操作守卫 403/200/404 符合预期。附注：非法 `date` 会断开连接（P2-1），不构成鉴权绕过 |
| R5.3 多用户隔离 | ✅ | `QF_WIRE_MULTIUSER=1` 下各用户数据落到 `data/users/<user>/`；路径穿越 header 被拒；非法 header 400 |
| R5.4 定时调度 | ✅ | `schedule --once` rc 0；禁用态 rc 3；非法 cron rc 3；日志文件正常写入；`serve --with-scheduler` 健康 |

## 4. 缺陷清单

### P0（阻断发布）

**P0-1 wheel 制品缺迁移 SQL / prompts / schema，安装后不可用**

- 复现：
  ```
  python -m pip wheel . --no-deps -w dist
  python -c "import zipfile;print(zipfile.ZipFile('dist/quota_fuse_wire-0.1.0-py3-none-any.whl').namelist())"
  python -m pip install dist/*.whl
  python -m qf_wire config validate      # rc 3
  python -m qf_wire run --sources-only   # rc 3
  python -m qf_wire history              # rc 3
  ```
- 预期：安装后 `config validate` rc 0，数据库自动建表，`history` 正常返回。
- 实际：wheel 共 65 个条目，`qf_wire/storage/migrations/` 下只有 `__init__.py`，`sql_migrations_in_wheel: []`，`has_schema_in_wheel: false`；安装后 `schema_dir_exists: false`；`config validate` 报 3 条 schema 缺失错误 rc 3；`run --sources-only` 报 `(sqlite3.OperationalError) no such table: source_scores` rc 3；`history` 报 `no such table: items` rc 3；`db_tables: ["schema_migrations"]`。
- 根因：`pyproject.toml` 的 `[tool.setuptools.package-data]` 仅声明 `qf_wire = ["web/static/*"]`；`storage/sqlite.py` 的 `MIGRATIONS_DIR` 指向包内目录、`config/validator.py:13` 的 `SCHEMA_DIR` 指向包外 `config/schema`、prompts 也在包外，三者都没有打包。
- 回归用例：`tests/unit/test_package.py::test_package_data_includes_sql_migrations`、`::test_prompts_live_inside_package`、`::test_schema_lives_inside_package`（均 xfail，strict=False）

### P1（功能缺失/不可用）

**P1-1 共用信源时前一赛道时间线丢失**

- 复现：两个 topic（semi、energy）引用同一个 `shared` 信源 → `run --sources-only` → 分别查两条事件的时间线。
- 预期：两条事件各自保留自己的时间线条目。
- 实际：semi 事件 `439d8a7fe07f277b` 时间线 **0 条**；energy 事件 `8ff15d773f4905fc` **2 条**；DB 中两条 item 的 `event_id` 都变成 `8ff1…`。
- 根因：`items` 以 `(day, url)` 唯一并按 url upsert，后写入的赛道覆盖了前一赛道的 `event_id`（`ux_items_day_url`）。
- 回归用例：`tests/integration/test_timeline_shared_source.py::test_shared_source_keeps_timeline_for_every_topic`（xfail）

**P1-2 干净根目录下 `config migrate` 不可用**

- 复现：空目录下 `qfw config migrate --legacy-dir <legacy>`。
- 预期：完成迁移。
- 实际：rc 3，`缺少配置文件: .../config/topics.yaml`。只有“就在原地升级”的场景会因为根回调先 `auto_migrate` 而 rc 0。
- 根因：`cli/main.py:46-77` 根回调在派发子命令**之前**就调用 `auto_migrate([Path.cwd(), paths.data_dir.parent], paths.config_dir)`，配置校验先于 `migrate` 子命令执行。
- 影响：文档推荐的新机迁移路径不可用。
- 回归用例：建议补充（本轮未加，需产品先确认预期行为）。

**P1-3 迁移不复制 `prompts/`，迁移后 `config validate` 失败**

- 复现：legacy 目录无 `prompts/` → `config migrate` → `config validate`。
- 预期：迁移生成可运行配置。
- 实际：rc 3，`提示词文件不存在: prompts/default.md`。`config/migrate.py:217-218` 写入了 `prompt_file: prompts/default.md`，但没有任何复制逻辑；`config/loader.py:186-233` 只解析路径不创建文件。
- 回归用例：现有 `tests/compat/test_legacy_migration.py` 的 `_prepare_prompt(root)` **预先创建了 `prompts/default.md`**，掩盖了该缺口；建议移除该预创建或新增“无 prompts 目录”用例。

**P1-4 仓库自带 `config/digest.yaml` 无法通过自带 schema**

- 复现：干净根目录 `qfw config validate`。
- 预期：rc 0。
- 实际：rc 3，`Additional properties are not allowed ('gateway' was unexpected)`。自带配置含顶层 `gateway:`（`base_url`/`api_key_env`），而 `config/schema/digest.schema.json:7` 为 `additionalProperties: false`。
- 影响：开箱即失败，直接影响 R2.7。

### P2（行为与契约不一致）

| 编号 | 问题 | 证据 / 位置 |
| --- | --- | --- |
| P2-1 | `/api/history?date=2026-13-99` 未捕获 `ValueError`，连接被直接断开（`RemoteDisconnected`），未返回 400 | `src/qf_wire/web/server.py:322`；用例 `tests/integration/test_dashboard_api.py::test_history_invalid_date_returns_400`（xfail） |
| P2-2 | 同端口重复启动 `qfw serve` 不报错，两个进程静默共存（`rc: None`）；`qfw mcp http` 端口冲突则正确 rc 3 | h9 证据 |
| P2-3 | 全部信源成功时 run 状态仍为 `partial`（`sources_unavailable: 0` 且 `exit_code: 0`） | h1/h12 证据 |
| P2-4 | 配置加载期失败绕过 `--output json`，仅输出 stderr，`stdout_len: 0` | h13 证据 |
| P2-5 | CLI 契约缺口：`--log-level nope` 被接受 rc 0；`digest` 无归档 rc 6、`digest --date 2026-13-01` rc 2、未知 topic rc 2、`history --days 0/-3` rc 2、`event show <unknown>` rc 6、`sources list --limit 200` 报 “No such option” rc 2、裸 `qfw event` rc 0 空输出、`serve` 绑定失败未映射退出码 | 见第 5 章 |
| P2-6 | 文档偏差：`WireEnvelope` 实际 11 字段而文档写 12；文档第 6 章引用不存在的 `tests/integration/test_cluster.py`（实际在 `tests/unit/core/test_cluster.py`） | `docs/REQUIREMENTS_TRACEABILITY.md` 第 5、6 章 |

### P3（体验 / 措辞）

1. `--log-level` 的合法位置与合法取值均无校验（任意值静默接受）。
2. 裸 `qfw event` 无子命令时静默 rc 0、无提示。
3. `qfw topics add --file` 强制要求 `keywords` 字段，与文档示例不一致。
4. `--limit` 参数存在但帮助文档缺失（且部分子命令不接受该参数）。

## 5. CLI 契约矩阵（第 3 章）

| 项目 | 契约 | 实测 | 结论 |
| --- | --- | --- | --- |
| 退出码 0 成功 | 0 | 0 | ✅ |
| 退出码 2 参数错误 | 2 | 2（未知 topic、非法 date、`history --days 0`） | ✅ |
| 退出码 3 配置错误 | 3 | 3（schema 非法、非法 cron、禁用调度） | ✅ |
| 退出码 4 全部信源失败 | 4 | 4 | ✅ |
| 退出码 8 部分失败 | 8 | 8（3 源里 1 源不可用） | ✅ |
| `--output json` | 合法 JSON | ✅（配置加载期失败除外，见 P2-4） | ◐ |
| `--output table` | 表格 | ✅ | ✅ |
| `--output csv` | CSV | ✅ | ✅ |
| 结果走 stdout、日志走 stderr | 分离 | ✅ | ✅ |
| `qfw mcp stdio` stdout 纯净 | 仅协议 | ✅（MCP Python SDK 客户端解析无杂质） | ✅ |
| 未在契约中的退出码 | 不应出现 | 6（`digest` 无归档、`event show` 未知 id） | ❌ 见 P2-5 |
| 裸命令 | rc 2 | 多数 rc 2；`qfw event` 为 0 | ◐ 见 P2-5 |
| `--log-level` 参数校验 | 非法值应 rc 2 | 任意值 rc 0 | ❌ 见 P2-5 |

## 6. 端到端主链路

顺序：干净安装 → `config validate` → `run` → `digest --date` → `history` → `event timeline` → `serve` → `qfw mcp` 四工具 → `config migrate`。

| 步骤 | 结果 |
| --- | --- |
| 源码树 `config validate` | rc 0 |
| `run` | rc 8（部分失败），采到 3 条，2 源 ok / 1 源 unavailable |
| `digest --date` | rc 0，走 fallback digest |
| `history` | rc 0，7 天；totals：items 3 / events 3 / multi_source 1 / digests 1 |
| `event list` | rc 0，3 条 |
| `event timeline` | rc 0，1 条，时间升序 |
| `serve` | `/` 200（45,420 B）、`/api/health` 200、`/data.js` 200（3,213 B） |
| `qfw mcp` | 4 工具可调，协议 `2025-11-25`，envelope 11 字段合法 |
| `config migrate`（legacy 夹具，无外部 clone） | 见下 |

**迁移保真度**：12 topics / 106 sources 全量保留，名称逐一比对 12/12 与 106/106 一致，`sum_topic_sources = 106`，无重复 id；仅两处 slug 规范化：`9to5mac → t_9to5mac`、`9to5google → t_9to5google`。`plaintext_secret_present: false`、`apikey_key_present: false`（`llm.config.json` 中的密钥已转为 `api_key_env` 引用）。legacy 文件权限 0o444，生成 `.migrated` 标记，重跑 `skipped: true`。**注意**：该链路在干净根目录不可用（P1-2），且不复制 prompts（P1-3）。

## 7. 配置能力

| 场景 | 结果 |
| --- | --- |
| 纯 YAML 新增 1 topic + 1 RSS source | `run --topic` rc 0，采到 2 条 |
| 非法 schema | rc 3，错误定位到字段 |
| topic 引用不存在的 source | rc 3，明确报错 |
| 非法 weight | rc 3，明确报错 |

## 8. 兼容对比

| 项目 | 结果 |
| --- | --- |
| `python fetch.py` | rc 8（预期部分失败） |
| `python digest.py` | rc 0 |
| `python server.py`（8793） | `/api/health` 200 |
| 旧版 `index.html` | 200（43,448 B），正常渲染 |
| `data/data.js` / `window.DATA` / `industries[].key` | 旧键全部保留 |
| 12 topics / 106 sources | 数量与名称逐条一致 |
| 看板降级标记 | 正常展示：`FEED_BAD：该源今日不可用` |
| `llm.config.json` 迁移 | 无明文密钥残留 |

## 9. 并发与稳定性

| 项目 | 结果 |
| --- | --- |
| 全量采集 3 次 | 每次 rc 8，约 0.8s，3 条，无 traceback |
| 单源超时注入 | rc 8，总耗时 1.82s，`feed_slow` 耗时 1,013ms 被隔离，其余源不受影响 |
| `serve` 读 + 并发 2 次 run 写 | 全部 rc 0，9 次探针正常，无锁错误 |
| 104+8+2 源并发采集（单测） | 3.04s，峰值并行 2–16，无连接泄漏 |

## 10. 文档偏差

1. 第 5 章称 `WireEnvelope` 为“12 字段”，实现为 11 字段（`domain, topic, event_id, data_as_of, payload, source, source_detail, fetched_at, freshness, confidence, source_status`）。
2. 第 6 章测试矩阵引用 `tests/integration/test_cluster.py`，该文件不存在，实际为 `tests/unit/core/test_cluster.py`。
3. CLI 第 3 章未列出的退出码 6 在实际中会出现（`digest` 无归档、`event show` 未知 id）。

## 11. 未覆盖与风险

- **R5.1 容器化**未验证（无 Docker）；建议在有 Docker 的 CI 上补跑。
- 未做真实公网 RSS 长周期稳定性测试（全部使用本地夹具，避免外部依赖与限流）。
- 未做性能压测（k6/JMeter 级别）；本轮只验证并发正确性与大致耗时。
- 未验证多用户并发写同一 DB 的极端场景（仅验证读并写与跨用户隔离）。
- 未安装 pyarrow，Parquet 归档仅验证降级路径。

## 12. 本轮新增/修改的测试

| 文件 | 内容 |
| --- | --- |
| `tests/integration/test_timeline_shared_source.py` | 新增：共用信源时间线丢失复现（xfail，P1-1） |
| `tests/integration/test_dashboard_api.py` | 追加：`/api/history` 非法 date 应返回 400（xfail，P2-1） |
| `tests/unit/test_package.py` | 追加：wheel 包内容断言（3 条 xfail，P0-1） |

全量回归：`231 passed, 5 xfailed in 29.14s`。

## 13. 修复优先级建议

1. **P0-1**：把 `storage/migrations/*.sql`、`config/schema/**`、`prompts/**` 纳入 wheel，并把 `SCHEMA_DIR` / prompts 定位改为包内路径（或安装时落盘）。
2. **P1-4**：自带 `digest.yaml` 与 schema 对齐（schema 允许 `gateway`，或配置改用 schema 允许的结构）。
3. **P1-2 / P1-3**：`config migrate` 应在子命令内完成迁移，并复制默认 prompts。
4. **P1-1**：item 与 event 的关联不应被 url upsert 覆盖，按 `(topic, day, url)` 或独立关联表建模。
5. P2/P3 按第 4 章顺序处理。
