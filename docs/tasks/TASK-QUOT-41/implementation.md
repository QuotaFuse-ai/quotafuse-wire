# QUOT-41 / M3 生态集成：实现报告

- 日期：2026-10-23
- 分支：`agent/QUOT-41-m3`
- 基线：M2 合并后的 `8908ba1`
- 关联契约：[`docs/MCP_TOOLS.md`](../../MCP_TOOLS.md)、[`docs/PROVIDER_INTEGRATION.md`](../../PROVIDER_INTEGRATION.md)
- 决策记录：[0004 MCP Server 回环与无数据语义](../../decisions/0004-mcp-server-loopback.md)

## 交付对照

| 需求 | 落地 | 验证 |
| --- | --- | --- |
| 1. WireEnvelope 契约固化 | `core/models.py`：11 个文档字段（`domain/topic/event_id/data_as_of/payload/source/source_detail/fetched_at/freshness/confidence/source_status`）；`extra="forbid"`；枚举用 `Literal` 严格校验；`fetched_at` 必须带时区 | `tests/contract/test_wire_envelope.py`（17 例：字段全集、必填、枚举越界、未知字段、朴素时间、序列化往返） |
| 2. WireProvider | `provider/wire_provider.py`：`get_digest / search_events / get_timeline / list_sources`，只读 `WireStore`，惰性配置，不 import Council 包 | `tests/contract/test_wire_provider.py`（23 例：别名、显式日期、未知赛道、未初始化库、窗口解析、时间线排序、空结果） |
| 3. Envelope 转换 | `provider/envelope.py`：`to_data_envelope` / `from_data_envelope`，`topic/event_id` 折叠进 `scope`；`tests/fixtures/council_stub.py` 提供最小 `data_access` 注册示例 | `tests/contract/test_envelope_mapping.py`（7 例：映射表逐项、digest/timeline 桩校验、往返、缺 `data_as_of`、注册后可取数） |
| 4. 模型网关复用 | `config/digest.yaml` 增加 `gateway.base_url`（`${QF_WIRE_MODEL_GATEWAY_URL}`）与 `api_key_env`；`config/loader.py` 展开 `${VAR}`；`pipeline/digest.py` 走 `gateway → claude-cli → 仅采集 partial` 链路；密钥只从环境变量读取，日志只输出状态码 | `tests/unit/pipeline/test_gateway.py`（6 例：成功用环境变量密钥、密钥不落日志、降级 claude-cli、双失败 partial、占位符未展开、配置展开） |
| 5. MCP Server | `mcp/server.py`（`MCPServer`，stdio / streamable-http，默认 `127.0.0.1:8791`）、`mcp/tools.py`（四个工具 + 参数校验 + 脱敏错误）、`cli/mcp.py`（`qfw mcp stdio\|http`） | `tests/contract/test_mcp_tools.py`（5 例：常量、stdio 四工具、参数错误、stdout 纯净性、HTTP 端到端） |
| 6. 生态对齐 | `scripts/export_sources.py` 统一输出 `{generated_at, topics, sources, scores?}`；赛道 id 用 slug、保留 `legacy_key`；prompt 未改边界规则 | 脚本实跑 + 既有 `tests/unit/cli/test_main.py` |
| 7. 测试 | 上述契约/单元测试 + 真实子进程 MCP 会话 | 全量 `146 passed in 17.78s` |
| 8. Agent Skill | `skills/quotafuse-wire/`：`SKILL.md`、`references/digest-format.md`、`examples/read-daily-brief.md`；README 增加“作为 Agent Skill 使用” | 按示例用真实 SDK 客户端走通 stdio；外部项目名扫描为 0 |

字段数量说明：issue 写“12 字段”但列出的字段为 11 个，`docs/` 与模型也是 11 个；实现以枚举出的 11 个字段为准，契约测试断言字段全集，防止后续悄悄增减。

## 实测一：真实 MCP stdio 会话

客户端：MCP Python SDK 2.3.0，`StdioServerParameters(command=python, args=["-m", "qf_wire", "mcp", "stdio"])`。服务端 stdout 每行由 SDK 保证为 JSON-RPC，日志在 stderr。

```text
initialize -> quota-fuse-wire 0.1.0
tools/list -> wire_get_digest, wire_search_events, wire_get_timeline, wire_list_sources

tools/call wire_get_digest isError=False
{"domain": "news", "topic": "semiconductor", "event_id": null, "data_as_of": "2026-10-22",
 "source": "wire", "source_detail": "feed_a,feed_b", "freshness": "archive",
 "confidence": "high", "source_status": "ok",
 "payload_keys": ["date", "error", "fallback", "generated_at", "items", "key_points",
                  "model", "partial", "provider", "status", "summary", "topic"]}

tools/call wire_search_events isError=False
{"domain": "news", "topic": "", "event_id": null, "data_as_of": "2026-10-22",
 "source": "wire", "source_detail": "feed_a,feed_b", "freshness": "archive",
 "confidence": "high", "source_status": "ok", "payload_keys": ["events", "query"]}

tools/call wire_get_timeline isError=False
{"domain": "news", "topic": "semiconductor", "event_id": "evt_20261022_1a2b3c",
 "data_as_of": "2026-10-22", "source": "wire", "source_detail": "feed_a,feed_b",
 "freshness": "archive", "confidence": "high", "source_status": "ok",
 "payload_keys": ["event", "timeline"]}

tools/call wire_list_sources isError=False
{"domain": "news", "topic": "semiconductor", "event_id": null, "data_as_of": "2026-10-22",
 "source": "wire", "source_detail": "feed_a,feed_b", "freshness": "archive",
 "confidence": "low", "source_status": "ok", "payload_keys": ["sources"]}

tools/call wire_get_digest(bad topic) isError=True
Error executing tool wire_get_digest: 未知赛道: no-such-topic（可用: semiconductor）
```

联调中发现并修复：`create_server()` 曾把 `WireConfig` 按位置传给 `WireTools(provider=...)`，导致工具内 `self._provider.config` 抛 `AttributeError`，SDK 统一包装为 `UnexpectedToolError`。改为关键字参数 `WireTools(config=config, ...)` 后四个工具全部通过。

## 实测二：Provider + DataEnvelope 桩

```python
from qf_wire.provider.wire_provider import WireProvider
from qf_wire.provider.envelope import to_data_envelope
from tests.fixtures.council_stub import DataAccessLayer

provider = WireProvider()
envelope = provider.get_digest("semiconductor")      # 别名解析到 semi
assert envelope.payload["items"]                      # 非空

data_access = DataAccessLayer(mapper=to_data_envelope)  # 最小 data_access 桩
data_access.register(provider)
consumed = data_access.get("wire", domain="news", topic="semi")
assert consumed.payload["items"]                      # 通过 CouncilDataEnvelope 校验
assert to_data_envelope(envelope)["scope"]["topic"] == "semi"
```

无数据、未知赛道、未初始化数据库三种情况均返回空 `payload` + `freshness=archive`，不抛异常；`tests/contract/test_wire_provider.py` 覆盖。

## 实测三：网关降级链

本地桩网关（OpenAI 兼容 `/chat/completions`）实跑 `qfw digest`：

- 配好 `QF_WIRE_MODEL_GATEWAY_URL` + `QF_WIRE_MODEL_GATEWAY_KEY`：`status=ok`、`partial=false`、`provider=gateway`，摘要与要点正常生成；
- 不配密钥：网关报“未配置模型网关密钥” → 降级 `claude-cli`；
- `claude-cli` 也不可用：`status=partial`、`partial=true`、`fallback=true`，保留 2 条采集结果，`summary` 为“模型当前不可用，未生成要点”。

三条路径分别由 `test_gateway_falls_back_to_claude_cli`、`test_gateway_and_claude_both_fail_is_partial`、`test_gateway_never_logs_key` 固化。

## 实测四：Agent Skill

- 三件套齐全，命令、工具名、字段名与实现一致；示例中的 CLI 路径用 `qfw --output json digest/event/sources`，MCP 路径用四个工具；
- 用示例中的调用序列（`wire_get_digest` → `wire_search_events` → `wire_get_timeline` → `wire_list_sources`）跑真实 SDK 客户端，返回同源信封；
- 外部项目名扫描：对 `skills/`、`README.md` 逐词检查历史项目名与改写说法，无命中。

## 测试

- 全量：`146 passed in 17.78s`（本机 Python 3.12.10，离线夹具，无外网）。
- 新增/相关：58 例
  - `tests/contract/test_wire_envelope.py`：17
  - `tests/contract/test_wire_provider.py`：23
  - `tests/contract/test_envelope_mapping.py`：7
  - `tests/contract/test_mcp_tools.py`：5
  - `tests/unit/pipeline/test_gateway.py`：6
- 既有回归：`tests/unit/cli/test_main.py` 更新为 `mcp` 子命令形态（`stdio` / `http`），退出码不变。

## 文档变更

- `docs/MCP_TOOLS.md`：`wire_get_timeline` 在事件不存在时的语义由“`isError: true`”改为“空 `payload` + `freshness=archive`”，与 Provider 的无数据约定一致；
- `README.md`：新增“作为 Agent Skill 使用”，修正 `wire_search_events` / `wire_list_sources` 的参数签名；
- `docs/decisions/0004-mcp-server-loopback.md`：记录 SDK 高层 API、回环绑定与无数据语义的取舍。

## 风险与后续

1. HTTP 模式无鉴权，只能本机绑定；若未来需要远程访问，必须补认证与 TLS；
2. 契约测试显式 `trust_env=False` 绕开系统代理；生产环境若走代理，需要确认回环地址在 `NO_PROXY` 内；
3. MCP SDK 2.x 的高层 API 仍在演进，升级时需回归 `tools/list`、`tools/call` 与 stdio 纯净性；
4. `wire_search_events` 的 `topic` 为空时返回跨赛道结果（`topic=""`），调用方需按事件内的 `topic` 归类；
5. `scripts/export_sources.py` 的评分依赖本地运行历史，新环境首次导出 `scores` 可能为空。

## 复现命令

```bash
# 全量测试（已在 Python 3.12 + mcp 2.3.0 下验证）
python -m pytest -q

# MCP stdio / http
qfw mcp stdio
qfw mcp http --port 8791        # 客户端连 http://127.0.0.1:8791/mcp

# Provider + 转换
python -c "from qf_wire.provider.wire_provider import WireProvider; \
print(WireProvider().get_digest('semiconductor').payload['items'][:1])"

# 降级链（不配密钥 -> claude-cli -> partial）
QF_WIRE_CLAUDE_BIN=/nonexistent/claude qfw digest --topic semiconductor --no-render
```

## 验收复核（项目领导人）

- 合入 `agent/QUOT-39-dashboard` 后全量测试：`172 passed`（含 QUOT-39 看板用例，M3 交付时 146 条）。
- Skill 三件套、MCP 四工具、信封 11 字段与实现逐项核对一致。
- `docs/REQUIREMENTS_v1.0.txt` 未改动；`src/qf_wire/core/errors.py` 仍保留 `EXIT_NOT_FOUND = 6`。
## 环境注意
- Windows 下 `mcp` 的 stdio 子进程走 Job Object，本机验证环境无 pywin32 时由 `deps/mcp/os/win32/utilities.py` 本地打补丁降级；仓库代码不受影响。
