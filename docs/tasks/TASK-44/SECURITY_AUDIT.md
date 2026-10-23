# 安全边界审计报告

- 日期：2026-10-23
- 关联任务：安全边界审计（父任务第 6 阶段）
- 基线：`adaeed8`
- 被测版本：`quota-fuse-wire` 0.1.0（`qfw` CLI / `qf_wire`）
- 审计范围：M1 Docker、M2 只读 API、M3 多用户、M4 MCP、配置迁移；对齐 `docs/REQUIREMENTS_v1.0.txt` 安全条款与第 13 章验证要求、`docs/DEPLOYMENT.md` 安全默认段
- 方法：白盒读码定位 + 本机黑盒 PoC 复现。所有 PoC 只对 `127.0.0.1` 上临时启动的被测进程或脚本自带桩服务发请求，不访问任何外部目标；金丝雀密钥均由脚本随机生成
- 产出：本报告 + `tests/security/` 下 5 个 PoC（共 47 条断言）

## 1. 结论摘要

**总判定：不通过。** 发现 3 项高危、5 项中危、8 项低危、8 项信息项。高危集中在写接口鉴权与多用户授权边界，均可用本机 PoC 稳定复现。

| 维度（issue 要求的四道闸门） | 结论 | 说明 |
| --- | --- | --- |
| 默认仅本机 | ⚠️ 部分满足 | 看板默认 `127.0.0.1`，但 `QF_WIRE_HOST/PORT` 环境变量被忽略；`--host 0.0.0.0` 无任何风险告警；`::1` 回环绑定直接失败；Docker 容器内固定监听 `0.0.0.0`，仅靠 compose 端口映射兜底 |
| 只读 API 有鉴权 | ✅ 满足（读）/ ❌ 不满足（写） | 读接口有 token + 回环旁路，非回环无 token 返回 403；写接口只校验回环来源和固定请求头 `X-Wire-Request: 1`，无任何凭据（SEC-01） |
| 敏感配置脱敏 | ⚠️ 部分满足 | 响应只返回 `hasKey/keyHint`，迁移不落明文 Key，`.env` 模板为空；但 DEBUG 日志记录完整查询串（SEC-14），且已存 Key 可被改 `apiBase` 后外发（SEC-02） |
| 多用户隔离 | ❌ 不满足 | 路径穿越被正确拦截，但 `X-QF-User` 只是“选用户”不是“认证用户”；任意回环客户端或同一个全局 token 可读所有用户的 `data.js` / `wire.db` / 归档 / 配置（SEC-03） |

| 等级 | 数量 | 编号 |
| --- | --- | --- |
| 严重 | 0 | — |
| 高 | 3 | SEC-01、SEC-02、SEC-03 |
| 中 | 5 | SEC-04 ～ SEC-08 |
| 低 | 8 | SEC-09 ～ SEC-16 |
| 信息 | 8 | SEC-17 ～ SEC-24 |

## 2. 风险总表

| 编号 | 等级 | 风险 | 关键位置 | PoC |
| --- | --- | --- | --- | --- |
| SEC-01 | 高 | 写接口无凭据，本地反代 / DNS rebinding 可远程写设置、触发任务 | `src/qf_wire/web/server.py:183-198,521-529` | `poc_write_surface.py` |
| SEC-02 | 高 | 改 `apiBase` 后触发提炼，已保存 API Key 随 `Authorization` 外发 | `src/qf_wire/web/server.py:382-447`、`src/qf_wire/config/ai.py:91-152`、`src/qf_wire/pipeline/digest.py:235-281` | `poc_key_exfil.py` |
| SEC-03 | 高 | `X-QF-User` 可任意选择租户，多用户无授权隔离 | `src/qf_wire/web/server.py:465-475`、`src/qf_wire/config/loader.py:46-55,207-242` | `poc_multiuser_isolation.py` |
| SEC-04 | 中 | Windows 保留设备名通过用户 id 校验，创建目录失败 | `src/qf_wire/config/loader.py:35,207-242` | `poc_multiuser_isolation.py` |
| SEC-05 | 中 | 信源 URL 未限制 scheme，`javascript:` 链接进入看板形成存储型 XSS | `src/qf_wire/sources/rss.py:30-41`、`sources/api.py:89`、`core/models.py:65-82`、`web/static/index.html.tpl:545,567` | `poc_input_and_bomb.py` |
| SEC-06 | 中 | 同步抓取助手 `_get` 只限制压缩后大小，gzip/deflate 解压无上限 | `src/qf_wire/sources/base.py:17,52-92` | `poc_input_and_bomb.py` |
| SEC-07 | 中 | 监听地址环境变量失效、非回环无告警、IPv6 回环不可用 | `src/qf_wire/cli/serve.py:14,39`、`cli/mcp.py:48`、`web/server.py:600-613`、`Dockerfile` | `poc_network_binding.py` |
| SEC-08 | 中 | MCP HTTP 无认证，绑定非回环时所有工具对外开放 | `src/qf_wire/mcp/server.py:84-94` | `poc_network_binding.py` |
| SEC-09 | 低 | 非 ASCII `Authorization` 触发未捕获 `TypeError`，连接被断开 | `src/qf_wire/web/server.py:496` | `poc_input_and_bomb.py` |
| SEC-10 | 低 | 写守卫用精确集合判断回环，与读守卫的 IP 解析不一致 | `src/qf_wire/web/server.py:38,46-52,521-523` | 代码审阅 |
| SEC-11 | 低 | 超大 `window` 后缀数值抛 `OverflowError`，MCP 未捕获 | `src/qf_wire/provider/wire_provider.py:416-425`、`mcp/tools.py:56-64` | `poc_input_and_bomb.py` |
| SEC-12 | 低 | `/api/digest`、`/api/sources`、`/api/events` 非法日期返回 404 而非 400 | `src/qf_wire/web/server.py:256-343,561-567` | 代码审阅 |
| SEC-13 | 低 | 响应缺少 CSP / `X-Frame-Options` / Referrer-Policy | `src/qf_wire/web/server.py:587-597` | 代码审阅 |
| SEC-14 | 低 | DEBUG 日志包含完整查询串，与部署文档承诺不符 | `src/qf_wire/web/server.py:219-220` | `poc_input_and_bomb.py` |
| SEC-15 | 低 | 多用户下 `qfw serve` 缺少用户入口；前端从不发送 `X-QF-User` | `src/qf_wire/cli/serve.py`、`web/static/index.html.tpl` | 代码审阅 |
| SEC-16 | 低 | `wire.db` 未显式收紧权限；`.env.local` 的 `chmod 0600` 在 Windows 无效 | `src/qf_wire/storage/sqlite.py`、`config/dotenv.py:137` | 代码审阅 |
| SEC-17 | 信息 | SQL 全部绑定参数，未发现注入；数据库可整体替换（WAL） | `src/qf_wire/storage/sqlite.py` | 代码审阅 |
| SEC-18 | 信息 | RSS 已前置拒绝 DOCTYPE/ENTITY；ElementTree 仍被 bandit 标记，建议 defusedxml | `src/qf_wire/sources/rss.py:89-100` | 代码审阅 |
| SEC-19 | 信息 | 密钥掩码、迁移不落明文、`.env` 空模板、忽略规则均正确 | `config/ai.py:59-64`、`config/migrate.py:216,310-311`、`.gitignore` | 代码审阅 + 密钥扫描 |
| SEC-20 | 信息 | Docker 以 root 运行、基础镜像未固定、配置卷可写；镜像中无密钥 | `Dockerfile`、`docker-compose.yml` | 代码审阅 |
| SEC-21 | 信息 | 依赖只有下界无锁文件；`pip-audit` 未发现已知漏洞；`httpx` 未声明在 dev extras | `pyproject.toml` | `pip-audit` |
| SEC-22 | 信息 | CI 只有 pytest，没有安全门禁 | `.github/workflows/ci.yml` | 代码审阅 |
| SEC-23 | 信息 | 包名/入口点与文档一致；MIT LICENSE 兼容 | `pyproject.toml:6-38`、`LICENSE` | 代码审阅 |
| SEC-24 | 信息 | 已确认的正向控制：读鉴权、请求体上限、路径穿越拦截、CORS 默认关闭、静态文件仅固定路径 | 多文件 | 代码审阅 + PoC |

## 3. 详细发现

### SEC-01（高）写接口无凭据：回环判断 + 固定请求头即可写入

**位置**
- `src/qf_wire/web/server.py:183-198`（`do_POST` / `_dispatch_post`）
- `src/qf_wire/web/server.py:521-529`（`_guard_write`）
- `src/qf_wire/web/static/index.html.tpl`（前端固定发送 `X-Wire-Request: 1`）

**问题**
`_guard_write` 只做两件事：`client_address[0]` 在 `LOOPBACK` 集合内，且请求头 `X-Wire-Request` 等于字符串 `"1"`。`"1"` 是写死在公开静态页里的常量，不构成任何秘密。读接口的 `QF_WIRE_API_TOKEN` / `QF_WIRE_API_REQUIRE_TOKEN` 对写接口完全不生效。服务端也不校验 `Host` / `Origin`。

因此以下场景可远程写入（无需本机恶意进程）：
1. 本机运行 nginx / SSH 隧道等反向代理，把外部请求转到 8790；
2. DNS rebinding：攻击者域名解析到 `127.0.0.1`，浏览器同源请求携带 `Host: attacker.example`，服务端不校验 Host；
3. 浏览器扩展、其他本地进程（同一用户权限）。

**复现**
```bash
python tests/security/poc_write_surface.py
```
结果：`poc_write_surface: 7/7 复现成功`。关键断言：
- 无 `X-Wire-Request` → 403；带 `X-Wire-Request: 1` → 200（无任何凭据）；
- 设置 `QF_WIRE_API_TOKEN` + `QF_WIRE_API_REQUIRE_TOKEN=1` 后，读接口 401，写接口仍 200；
- 通过本机 `127.0.0.1` 转发模拟反向代理，伪造 `Host: attacker.example`、`X-Forwarded-For: 203.0.113.9`、`Origin: https://attacker.example`，写接口仍 200。

**影响**
未授权修改模型配置、触发提炼任务；与 SEC-02 串联可窃取已保存的模型 API Key。写接口还包含 `/api/digest/run`，可被用于资源消耗。

**修复建议**
1. 写接口在配置了 `QF_WIRE_API_TOKEN` 时必须校验 Bearer；建议引入独立的 `QF_WIRE_ADMIN_TOKEN`，并让 `QF_WIRE_API_REQUIRE_TOKEN` 同时覆盖读写。
2. 校验 `Host` 白名单（`127.0.0.1`、`localhost`、`[::1]` 及显式配置的看板域名），拒绝其他 Host，防 DNS rebinding。
3. 启动时为进程生成随机 CSRF token，注入 `/` 页面，写请求校验 `X-Wire-Request: <token>`，把该头从“常量标记”改为“会话秘密”。
4. 在文档中明确：回环来源不等于身份认证。

**验证方式**
修复后重跑 `poc_write_surface.py`，期望：无凭据写 → 401/403；伪造 Host → 403；带合法 token + CSRF → 200。并补充 `tests/unit/test_web_guard.py` 回归用例。

---

### SEC-02（高）已保存 API Key 可被改 `apiBase` 后外发

**位置**
- `src/qf_wire/web/server.py:382-400`（`/api/settings` 保存）
- `src/qf_wire/web/server.py:402-447`（`/api/digest/run`）
- `src/qf_wire/config/ai.py:109-142`（`effective_key = key_value or existing_key`，未提交 Key 时沿用旧 Key）
- `src/qf_wire/pipeline/digest.py:235-281`（`_post_chat` 把 Bearer Key 发往 `apiBase`）

**问题**
攻击者只需两步：`POST /api/settings` 把 `apiBase` 改到自己的地址（不提交 `apiKey`，服务端沿用已保存 Key 并返回 `hasKey: true`），再 `POST /api/digest/run`。后台任务随后把 `Authorization: Bearer <已保存 Key>` 发往攻击者地址。`apiBase` 仅要求 `http(s)://`，没有对回环/私网/链路本地/云元数据地址做任何限制，也没有“改地址需重新输入 Key”的约束。

**复现**
```bash
python tests/security/poc_key_exfil.py
```
结果：`poc_key_exfil: 9/9 复现成功`。PoC 先在不可达地址保存随机金丝雀 Key，再只改 `apiBase`（不带 Key），触发提炼；本机桩服务在 `Authorization` 头中收到该 Key，路径为 `/v1/chat/completions`。

**影响**
高价值模型 Key 泄露；Key 可被用于消耗额度或横向访问模型网关。若攻击者把 `apiBase` 指向云元数据地址（如 `169.254.169.254`），还可能形成 SSRF，但当前只发 POST JSON、且不返回响应体给攻击者，主要危害仍是密钥外发。

**修复建议**
1. 修改 `apiBase` 时要求重新输入 Key 或二次确认（本地交互），禁止“只改地址沿用旧 Key”。
2. 对 `apiBase` 做 SSRF 防护：默认拒绝回环、私网、链路本地、`169.254.169.254`、`.internal`；需要时用显式 allowlist 放行。
3. 仅允许 `https://` 持久化（保留 `http://127.0.0.1` 作为本地调试例外）。
4. 写设置与触发任务时记录审计日志（不含 Key），并对异常地址变更告警。

**验证方式**
重跑 `poc_key_exfil.py`，期望：只改 `apiBase` 被 400 拒绝；桩服务收不到 Key；合法 https + 重新输入 Key 时任务正常。补充单测覆盖 `save_ai_settings` 的地址策略。

---

### SEC-03（高）`X-QF-User` 不是认证，多用户无授权隔离

**位置**
- `src/qf_wire/web/server.py:465-475`（`_resolve_request_config` 直接信任头部）
- `src/qf_wire/config/loader.py:46-55`（`resolve_user` 只做字符校验）
- `src/qf_wire/config/loader.py:207-242`（`resolve_paths` 指向 `data/users/<user>`）
- 现有契约测试：`tests/integration/test_dashboard_api.py:276-312`（把“任意回环客户端可读任意用户”固化为预期）

**问题**
多用户模式下，每个请求通过 `X-QF-User` 选择数据目录。服务端只验证 id 的字符集与长度，不验证调用者是否有权访问该用户。读接口的回环旁路、以及单一全局 `QF_WIRE_API_TOKEN`，都会让任意调用者读取所有用户的 `data.js`、`wire.db`、归档与用户级配置。路径穿越本身被正确拦截（这是唯一有效的控制）。

**复现**
```bash
python tests/security/poc_multiuser_isolation.py
```
结果：`poc_multiuser_isolation: 16/16 复现成功`。关键断言：
- 回环客户端改一个头即可读 alice / bob 的 `data.js` 与 `/api/history`；
- 配置同一个全局 token 后，同一 token 可读两个用户；
- 对照：`../escape`、`café`、65 字符、`..`、`a/b` 均被 400 拒绝。

**影响**
多租户场景下用户数据完全互通，违反 M3 隔离目标；若服务通过反代暴露，任何持有全局 token 的外部调用者都能遍历用户数据。

**修复建议**
1. 引入“主体 → 用户”的映射：每用户 token（配置或 `users.yaml`，至少哈希存储），认证后由服务端决定用户目录；`X-QF-User` 仅作为已认证主体的可选子选择。
2. 非回环请求禁止自选用户；回环旁路在 `QF_WIRE_API_REQUIRE_TOKEN` 下也应关闭。
3. 保持现有 id 正则与路径解析，补 Windows 保留名（见 SEC-04）。
4. 修改 `tests/integration/test_dashboard_api.py` 的既有预期属于契约变更，需领导人确认后单独 PR。

**验证方式**
重跑 `poc_multiuser_isolation.py`，期望：无凭据/错误 token 读他人数据 → 401/403；正确 token 仅能读本人；全局 admin 才可跨用户。补充每用户授权单测。

---

### SEC-04（中）Windows 保留设备名通过用户 id 校验

**位置**：`src/qf_wire/config/loader.py:35,207-242`

**问题**：`USER_ID_PATTERN` 允许 `CON`、`AUX`、`NUL`、`PRN` 等 Windows 保留设备名。`resolve_user` 接受这些 id，后续 `mkdir` 用户目录时 Windows 报 `NotADirectoryError WinError 267`（本机 Windows 实测）。

**复现**：`poc_multiuser_isolation.py` 断言四个保留名均通过正则；Windows 上 `resolve_paths(..., user="CON").ensure()` 抛 `OSError`。

**影响**：多用户模式下特定用户 id 无法创建目录，属于功能性拒绝服务；影响仅限 Windows 本地，且需要能设置用户名。

**修复建议**：id 校验增加保留名黑名单（大小写不敏感）：`CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]`，同时拒绝结尾的点与空格；在 Windows 上补单测。

**验证方式**：`resolve_user("CON")` 抛 `ConfigError`；Windows 新建用户正常。

---

### SEC-05（中）信源 URL 未限制 scheme，形成存储型 XSS

**位置**
- `src/qf_wire/sources/rss.py:30-41`（`_link` 直接返回 `<link>` 内容）
- `src/qf_wire/sources/api.py:89`（`urljoin` 后不校验 scheme）
- `src/qf_wire/core/models.py:65-82`（`SourceItem.url` 无校验）
- `src/qf_wire/web/static/index.html.tpl:545,567`（`link.href = report.url / item.url`）

**问题**：RSS/API 中的 `javascript:`、`data:` 链接被原样保存，并在看板中赋给 `href`。用户点击后在看板同源执行脚本，可调用 SEC-01 的写接口、读取当前用户数据。HTML 适配器有 scheme 过滤，RSS/API 没有。

**复现**：`poc_input_and_bomb.py` 断言 `javascript:` 链接原样保留在 `SourceItem.url`。

**影响**：需要攻击者控制一个已配置信源（或信源被投毒）并诱导用户点击；点击后可在看板源内执行任意脚本。

**修复建议**：在 `SourceItem` 增加 `http/https` scheme 校验（`urljoin` 之后），非法链接丢弃或降级为纯文本；模板加 `rel="noopener noreferrer"`；补 CSP（SEC-13）。

**验证方式**：构造 `javascript:` 条目的 RSS/API fixture，断言被丢弃或改写；UI 中点击不再执行脚本。

---

### SEC-06（中）同步 `_get` 存在 gzip/deflate 解压炸弹

**位置**：`src/qf_wire/sources/base.py:17,52-92`

**问题**：代码先读压缩后字节并检查 `len(raw) > MAX_BYTES`，随后无上限调用 `gzip.decompress` / `zlib.decompress`。16 MB 解压数据只需约 16 KB 压缩体，可绕过 8 MB 限制。

**范围说明**：内置适配器走 `pipeline/fetch.py:140-190` 的 aiohttp 路径，aiohttp 默认流式解压且 `_read_limited` 对解压后分块累计限流，**不受影响**。受影响的是自定义适配器按 `docs/SOURCES.md` 实现 `fetch()` 时复用的同步助手 `_get`（`pipeline/fetch.py:147` 会回退到线程执行）。

**复现**：`poc_input_and_bomb.py` 用本机桩服务返回 16 MB 的 gzip 响应，`RSSAdapter._get()` 返回 `16777216` 字节，超过 `MAX_BYTES=8388608`。

**影响**：自定义适配器场景下内存耗尽/进程崩溃；属于本地或已配置信源的可用性风险。

**修复建议**：拒绝 `Content-Length > MAX_BYTES`；使用 `zlib.decompressobj().decompress(data, MAX_BYTES + 1)` 限制解压输出，超限即报错；同步助手与异步路径共用同一限流工具。

**验证方式**：解压炸弹响应应抛 `SourceError`，内存不增长；正常 gzip 响应仍可解析。

---

### SEC-07（中）监听配置与文档不一致、无暴露告警、IPv6 回环不可用

**位置**
- `src/qf_wire/cli/serve.py:14,39`（只读 CLI `--host`，不读 `QF_WIRE_HOST`）
- `src/qf_wire/cli/mcp.py:48`（同样问题）
- `src/qf_wire/web/server.py:600-613`（仅打印“看板已启动”，不告警）
- `Dockerfile`（`CMD ... --host 0.0.0.0`）、`docker-compose.yml`（环境变量 `QF_WIRE_HOST=0.0.0.0` 实际无效）

**问题**
1. `QF_WIRE_HOST/PORT`、`QF_WIRE_MCP_HOST/PORT` 在 `.env`、compose 中均有定义，但 CLI 不读取，操作者以为改环境变量即可控制监听地址；
2. 显式 `--host 0.0.0.0` 启动时没有任何“已暴露到非回环”的 WARNING；
3. `ThreadingHTTPServer` 固定 `AF_INET`，`--host ::1` 在 Linux 报 `Address family for hostname not supported`，不满足“IPv4/IPv6 双回环默认仅本机”的要求；
4. 容器内固定 `0.0.0.0`，安全性完全依赖 compose 的 `127.0.0.1:8790:8790` 映射；用户执行 `docker run -p 8790:8790` 会直接暴露。

**复现**：`poc_network_binding.py` 断言：`QF_WIRE_HOST=0.0.0.0` 被忽略；0.0.0.0 启动无告警；`create_server(..., "::1", 0)` 失败；MCP HTTP 无鉴权参数。

**影响**：运维误配置导致看板/MCP 暴露到局域网或公网；IPv6-only 环境不可用。

**修复建议**：CLI 默认值读取环境变量（CLI 显式参数优先）；非回环绑定时打印醒目 WARNING 并要求 `--allow-remote` 显式确认；支持 `::1`（按地址族选择 `AF_INET6`，或同时监听两个套接字）；Docker 文档强制 `-p 127.0.0.1:...`，或容器内默认只监听 `127.0.0.1` 并提供显式放开选项。

**验证方式**：新增单测/CLI 测试覆盖环境变量优先级与告警；Linux 上 `--host ::1` 可正常服务。

---

### SEC-08（中）MCP HTTP 无认证

**位置**：`src/qf_wire/mcp/server.py:84-94`

**问题**：`run_http` 直接 `create_server(...).run("streamable-http", host, port)`，没有 token、Host 校验或来源限制；默认 `127.0.0.1` 是唯一保护。一旦按文档改绑 `0.0.0.0`，所有只读工具（digest/search/timeline）对外开放。

**复现**：`poc_network_binding.py` 启动真实 `qfw mcp http` 子进程，未携带任何凭据 POST `/mcp` 的 `initialize`，返回 HTTP 200 且无 `WWW-Authenticate`。

**影响**：数据泄露（资讯内容、事件时间线、提炼结果）；与 DNS rebinding 结合可由浏览器页面读取。当前 compose 未启动 MCP HTTP 进程，默认路径下风险有限。

**修复建议**：复用 `QF_WIRE_API_TOKEN` 作为 MCP HTTP Bearer；未配置 token 时拒绝绑定非回环；校验 Host；文档默认推荐 stdio。

**验证方式**：无 token 请求 → 401；带 token → 200；非回环无 token 启动被拒绝。

---

### SEC-09（低）非 ASCII `Authorization` 触发未捕获 `TypeError`

**位置**：`src/qf_wire/web/server.py:496`

**问题**：`secrets.compare_digest(value.strip(), token)` 对含非 ASCII 字符的 `str` 会抛 `TypeError`，服务端未捕获，连接被直接断开并在 stderr 打印堆栈。

**复现**：`poc_input_and_bomb.py` 发送 `Authorization: Bearer ÿ`，客户端收到 `RemoteDisconnected`；ASCII token 对照正常 200。

**影响**：单请求即可制造异常与日志噪音；不构成鉴权绕过。

**修复建议**：比较前统一编码为 bytes（`value.encode("utf-8", "surrogateescape")`），或捕获 `TypeError` 返回 401。

**验证方式**：非 ASCII 头返回 401，连接不中断。

---

### SEC-10（低）写守卫与读守卫的回环判断不一致

**位置**：`src/qf_wire/web/server.py:38,46-52,521-523`

**问题**：读路径用 `_is_loopback`（IP 解析，包含 `::ffff:127.0.0.1`），写路径用精确集合 `LOOPBACK`。当前服务是 `AF_INET`，影响有限；将来启用 IPv6 双栈后，IPv4-mapped 回环客户端会被写接口拒绝。

**修复建议**：写守卫统一调用 `_is_loopback(client)`。

**验证方式**：单测覆盖 `::ffff:127.0.0.1` 与 `localhost` 场景。

---

### SEC-11（低）超大 `window` 数值抛 `OverflowError`

**位置**：`src/qf_wire/provider/wire_provider.py:416-425`、`src/qf_wire/mcp/tools.py:56-64`

**问题**：`parse_window` 用 `int()` 解析后直接构造 `timedelta(days=amount)`；`999999999999999999d` 抛 `OverflowError`。MCP 工具只捕获 `ValueError`。

**复现**：`poc_input_and_bomb.py` 断言 `parse_window` 与 `wire_search_events` 均抛 `OverflowError`。

**影响**：MCP 调用方收到未处理异常/堆栈；不涉及代码执行。

**修复建议**：在 `parse_window` 限制上限（如 3650 天）并转换为 `ValueError`；工具层捕获该异常返回参数错误。

**验证方式**：超大 window 返回明确错误，进程不中断。

---

### SEC-12（低）部分接口非法日期返回 404

**位置**：`src/qf_wire/web/server.py:256-343,561-567`

**问题**：`/api/history` 已在缺陷修复中改为 400，但 `/api/digest`、`/api/sources`、`/api/events` 仍经 `_resolve_day` 把非法日期吞成 `None`，返回 404“无数据”，语义误导。

**修复建议**：统一在入口校验 `date`，非法返回 400。

**验证方式**：三个接口 `?date=2026-13-40` 均返回 400。

---

### SEC-13（低）缺少 CSP / `X-Frame-Options`

**位置**：`src/qf_wire/web/server.py:587-597`

**问题**：已设置 `Cache-Control: no-store`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: no-referrer`，但无 CSP、无 `X-Frame-Options`。页面可被第三方 iframe 嵌套（点击劫持），也缺少对 SEC-05 的纵深防御。

**修复建议**：增加 `Content-Security-Policy`（先 Report-Only，处理内联脚本/样式后收紧）、`X-Frame-Options: DENY`。

**验证方式**：响应头检查；页面功能回归。

---

### SEC-14（低）DEBUG 日志记录完整查询串

**位置**：`src/qf_wire/web/server.py:219-220`

**问题**：`log_message` 记录完整请求行（含 query）。`poc_input_and_bomb.py` 以 `?api_key=poc-query-canary` 请求，断言金丝雀出现在 DEBUG 日志中。`docs/DEPLOYMENT.md` 承诺日志不打印完整查询串。

**影响**：若用户把 token/Key 放在 query（例如错误的集成方式），会落入日志文件。

**修复建议**：只记录 `urlparse(path).path`，或对 `token/key/api_key/authorization` 等参数脱敏；同步更新文档或代码使其一致。

**验证方式**：带敏感 query 的请求日志中不出现该值。

---

### SEC-15（低）多用户模式缺少 CLI/前端用户入口

**位置**：`src/qf_wire/cli/serve.py`、`src/qf_wire/web/static/index.html.tpl`

**问题**：开启 `QF_WIRE_MULTIUSER=true` 后，`qfw serve` 启动需要 `QF_WIRE_USER`，否则路径解析报错；前端从不发送 `X-QF-User`，默认只能看默认用户。属于功能完整性问题，与 SEC-03 的授权缺失不同。

**修复建议**：`qfw serve` 增加 `--user` 选项或明确的环境变量提示；前端在多用户模式下从路由/配置注入用户头（需先完成 SEC-03 的认证设计）。

---

### SEC-16（低）本地数据文件权限未收紧

**位置**：`src/qf_wire/storage/sqlite.py`（创建 DB 未设置 0600）、`src/qf_wire/config/dotenv.py:137`（`chmod(0o600)` 在 Windows 无效）

**问题**：`wire.db`、归档、`.env.local` 依赖系统默认权限/ACL。Windows 上 `chmod` 不生效，同机其他本地用户是否能读取决于目录 ACL。

**影响**：本地多账户主机上的数据暴露；远程攻击面不直接相关。

**修复建议**：创建文件后显式收紧权限（POSIX `0600`，Windows 记录并依赖用户目录 ACL）；文档说明 Windows 下的权限模型。

---

### SEC-17（信息）SQLite 查询与数据库替换

**位置**：`src/qf_wire/storage/sqlite.py`

**结论**：所有 SQL 使用 `text(...)` + 绑定参数，未发现字符串拼接注入；`query.get("topic")` 等任意值只会作为绑定参数。数据库为单文件 `wire.db`（WAL），可随 `data/` 整体替换，属于预期行为。未发现反序列化入口（纯 JSON/YAML/SQLite）。

### SEC-18（信息）XXE / XML 解析

**位置**：`src/qf_wire/sources/rss.py:89-100`

**结论**：解析前检查前 8192 字节，拒绝 `<!DOCTYPE` 与 `<!ENTITY`，可阻断经典 XXE；bandit 的 B405/B314 仍会告警。建议改用 `defusedxml.ElementTree` 作为纵深防御，并与 bandit 基线对齐。

### SEC-19（信息）密钥处理的正向结论

- `read_ai_settings` 只返回 `hasKey/keyHint`，`mask_key` 对长度 ≤8 全部打码，否则首 3 末 4；`/api/settings` 响应不含明文（PoC 已断言）。
- `config migrate` 仅写 `api_key_env` 引用，报告“apiKey 未写入磁盘”。
- 仓库内 `.env` 为空模板；`.env.local`、`config/*.local.yaml`、`data/` 已在 `.gitignore`；对跟踪文件做密钥正则扫描（`sk-...`、`api_key=...`）无命中。
- 读接口 token 使用 `secrets.compare_digest`（常量时间），`Authorization` 不进入应用日志（但 query 日志见 SEC-14）。

### SEC-20（信息）容器与发布

- `Dockerfile` 以 root 运行，基础镜像 `python:3.12-slim` 未固定 digest；`config` 卷可写；未设置 `USER`。建议非 root 用户、固定基础镜像摘要、只读挂载配置。
- 镜像构建未注入密钥（无 `ARG`/`COPY .env`），compose 中密钥通过运行时环境变量注入。
- compose 端口映射已限制 `127.0.0.1`，这是当前唯一有效的网络防护；`QF_WIRE_HOST/MCP_HOST` 在容器内为 `0.0.0.0` 且代码不读环境变量（SEC-07）。

### SEC-21（信息）依赖与供应链

- `pyproject.toml` 依赖只有下界，无 lock/hash；建议生成锁文件并在 CI 使用 `--require-hashes` 或至少固定版本。
- `pip-audit`：**No known vulnerabilities found**（78 个依赖，本地包 `quota-fuse-wire` 不在 PyPI，跳过）。
- `httpx` 被 `tests/contract/test_mcp_tools.py` 使用，但不在 `[dev]` extras，干净环境会收集失败；应显式声明。
- bandit：10 条 High，逐条复核均为误报或已接受风险：B324 SHA1（去重指纹/迁移短 id，非安全用途）、B404/B603（`subprocess.run` 固定 argv、无 shell、输入为模型名与提示词）、B310（`urlopen` 仅用于 http(s) 且 URL 来自配置）、B405/B314（RSS 已前置拒绝 DTD/ENTITY）。

### SEC-22（信息）CI 安全门禁

`.github/workflows/ci.yml` 仅运行 `pytest`。建议增加：`pip-audit`、`bandit`（带基线）、密钥扫描（gitleaks）、以及本报告 `tests/security/` 的只读 PoC 回归（或将其转为 pytest 用例）。

### SEC-23（信息）包名与许可证

`pyproject.toml`：`name = "quota-fuse-wire"`，入口 `qfw` / `quota-fuse-wire` 均指向 `qf_wire.cli.main:main`，与 README/部署文档一致；`LICENSE` 为 MIT，与依赖许可证兼容。安装只覆盖这两个命令，未发现与其他包的入口冲突。

### SEC-24（信息）已确认的正向控制

- 读鉴权：非回环无 token → 403；token 错误 → 401；常量时间比较。
- 请求体上限 16 KB，仅接受 JSON object；`days` 上限 365；`MAX_ITEMS` 限制条目数。
- 路径穿越：用户 id 正则 + `resolve_paths`，`../`、`..`、`/`、非 ASCII、超长均 400。
- CORS：默认为空，仅显式 allowlist 回显 Origin。
- 静态文件：仅按固定路由读取 `STATIC_DIR` 下文件，无用户可控路径拼接。
- 响应头：`no-store`、`nosniff`、`no-referrer`（缺 CSP/XFO，见 SEC-13）。

## 4. 四道闸门判定

| 闸门 | 判定 | 依据 |
| --- | --- | --- |
| 默认仅本机 | ⚠️ 部分满足 | 看板默认 `127.0.0.1`；但环境变量失效、无暴露告警、IPv6 回环不支持、容器固定 `0.0.0.0`（SEC-07） |
| 只读 API 有鉴权 | ✅ 读 / ❌ 写 | 读接口有 token 与回环旁路；写接口只有常量头（SEC-01、SEC-02） |
| 敏感配置脱敏 | ⚠️ 部分满足 | 展示与迁移脱敏正确（SEC-19）；但 Key 可被改 `apiBase` 外发（SEC-02），DEBUG 记录完整 query（SEC-14） |
| 多用户隔离 | ❌ 不满足 | `X-QF-User` 未认证，任意回环/全局 token 可跨用户读取（SEC-03）；路径穿越已防住，Windows 保留名有功能缺陷（SEC-04） |

**上线建议**：SEC-01、SEC-02、SEC-03 修复并复测通过前，不建议把看板通过任何反代/DNS 暴露到本机之外，也不建议在多用户场景下存放不同用户的敏感信源。三项高危按 24 小时 SLA 处理。

## 5. 基线与工具结果

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 单元/集成测试 | `python -m pytest -q` | **237 passed**（29.06s） |
| 依赖漏洞 | `python -m pip_audit` | **No known vulnerabilities found** |
| 静态扫描 | `python -m bandit -q -r src` | 10 High，全部人工复核为误报/已接受（SEC-21） |
| 密钥扫描 | `git grep` 正则（`sk-*`、`api_key=` 等，排除 tests/docs） | 无命中 |
| 安全 PoC | 见下表 | **47/47 断言通过** |

| PoC | 断言 | 结果 |
| --- | --- | --- |
| `tests/security/poc_write_surface.py` | 7 | 7/7 |
| `tests/security/poc_key_exfil.py` | 9 | 9/9 |
| `tests/security/poc_input_and_bomb.py` | 8 | 8/8 |
| `tests/security/poc_multiuser_isolation.py` | 16 | 16/16 |
| `tests/security/poc_network_binding.py` | 7 | 7/7 |

环境：WSL Ubuntu 24.04 / Python 3.12.3（`/tmp/qfvenv`，`pip install -e ".[dev]"` + `httpx`）。Windows 专属行为（保留设备名、`chmod` 无效）在本机 Windows Python 上单独验证。

## 6. PoC 使用说明

```bash
# 在仓库根目录，使用已安装 dev 依赖的虚拟环境
python tests/security/poc_write_surface.py
python tests/security/poc_key_exfil.py
python tests/security/poc_input_and_bomb.py
python tests/security/poc_multiuser_isolation.py
python tests/security/poc_network_binding.py
```

- 每个脚本自建临时目录、临时看板/桩服务，全部监听 `127.0.0.1`，退出即清理；不发任何外部请求。
- 密钥为随机金丝雀（`poc-canary-<hex>`），脚本内不包含真实密钥。
- 断言失败时以退出码 1 结束，可直接用于 CI（建议纳入安全回归 job）。
- `poc_network_binding.py` 会启动真实 `qfw mcp http` 子进程，结束后终止自身子进程；不修改系统配置。

## 7. 未覆盖 / 限制

- Docker 运行时未在本机验证（Docker 不可用），容器相关结论来自 Dockerfile/compose 静态审阅。
- 未对模型网关、claude CLI 做外部联调；PoC 使用本机桩服务验证数据流。
- 未做真实 Windows 浏览器 UI 的 XSS 点击验证，仅验证数据流（非法 scheme 保留到 `href`）；建议修复后用浏览器复测。
- 多用户授权模型涉及产品契约（现有测试固化了当前行为），修复需领导人确认后单独 PR，本报告不改业务逻辑。
- 未进行压力/DoS 测试（除压缩炸弹外），未对外部目标做任何扫描。
