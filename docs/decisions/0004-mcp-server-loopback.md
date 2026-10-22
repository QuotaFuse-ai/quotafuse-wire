# 0004 MCP Server：SDK 高层 API + 本机回环 + 无数据不报错

- 状态：已采纳（M3）
- 日期：2026-10-23
- 相关：`src/qf_wire/mcp/server.py`、`src/qf_wire/mcp/tools.py`、`tests/contract/test_mcp_tools.py`、`docs/MCP_TOOLS.md`

## 背景

M3 要求 Wire 同时支持 `qfw mcp stdio` 与 `qfw mcp http --port 8791`，暴露四个只读工具，返回统一的 `WireEnvelope`；stdio 的 stdout 只能是 JSON-RPC。实现需要在 MCP SDK 版本、HTTP 默认监听范围、以及“查无数据”语义上做取舍。

## 决策

1. 使用 MCP Python SDK 的高层 `MCPServer`：`@server.tool(name=..., description=...)` 声明工具，`run("stdio")` / `run("streamable-http", host=..., port=...)` 启动传输，不手写 JSON-RPC 分发；
2. 工具内部只通过 `ToolError` 表达可读的参数错误，其它异常统一包装为脱敏消息；不在工具里 `print`，日志 handler 全部指向 stderr；
3. HTTP 默认 `127.0.0.1:8791`，端口常量 `DEFAULT_HTTP_PORT = 8791`；`qfw mcp http` 不提供公网绑定默认值；
4. “查无数据”不是错误：无归档、未知赛道、事件不存在时返回空 `payload` + `freshness=archive`（搜索类保留 `{"query": ..., "events": []}`），与 `WireProvider` 的约定一致；只有参数缺失/格式错误与数据库未初始化返回 `isError: true`；
5. 契约测试用真实 SDK 子进程完成 `initialize → tools/list → tools/call`；HTTP 测试显式传入 `httpx.AsyncClient(trust_env=False)`，绕开系统代理直连回环地址。

## 理由

- 高层 API 与 Council 侧可能的 SDK 客户端保持同一协议实现，避免自维护 JSON-RPC 层；
- stdio 纯净性由 SDK 保证，工具层只需守住“不写 stdout”这一条；
- 只监听本机符合“数据不出本机、Council 通过本地文件共享”的边界；
- 查无数据返回空信封，调用方可以按“无资讯”处理，不需要区分异常路径，降低集成成本；
- Windows 上 httpx 会读取注册表代理（如 `127.0.0.1:10809`），若不绕开，回环请求会被代理拦截并返回 503。

## 被否方案

| 方案 | 否因 |
| --- | --- |
| 手写 stdio JSON-RPC 循环 | 重复实现握手、能力协商与错误码，易破坏协议纯净性 |
| 事件不存在时返回 `isError: true` | 与 Provider“无数据不抛异常”的约定冲突，调用方需额外分支 |
| HTTP 默认监听 `0.0.0.0` | 超出“本机优先”边界，且无鉴权 |
| 测试沿用系统代理 | 本机回环不应依赖代理配置，测试环境不可复现 |

## 代价与风险

- 高层 API 绑定 SDK 版本（当前 2.x）；升级 SDK 时需回归四个工具与 stdio 纯净性测试；
- HTTP 模式没有鉴权，只允许本机绑定，若未来需要远程访问必须另加认证与 TLS；
- “无数据不报错”让客户端难以区分“没有归档”和“事件 id 写错”，需依赖 `payload` 为空与文档说明。
