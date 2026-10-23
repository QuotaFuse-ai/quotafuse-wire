# QUOT-42 / M4 产品化：实现报告

- 日期：2026-10-23
- 分支：`agent/QUOT-39-dashboard`
- 关联规格：[`docs/DEPLOYMENT.md`](../../DEPLOYMENT.md)、[`docs/CONFIG.md`](../../CONFIG.md)
- 决策记录：[0005 多用户目录与 API 鉴权默认值](../../decisions/0005-multiuser-and-api-auth.md)、[0006 请求身份绑定与写令牌](../../decisions/0006-request-identity-binding.md)（0006 取代 0005 第 3、8 条）

## 交付对照

| 需求 | 落地 | 验证 |
| --- | --- | --- |
| R5.1 Docker Compose 一键部署 | `docker-compose.yml`、`Dockerfile`：`docker compose up -d` 启动 `qfw serve --with-scheduler`，`./data` / `./config` 挂载，端口只映射到宿主机回环 | `docs/DEPLOYMENT.md` 部署步骤；`/api/health` 存活探测 |
| R5.2 只读 API 默认仅本机 | `web/server.py`：`_guard_host` 校验 `Host` 头防 DNS rebinding，`_guard_read` 校验 socket 对端地址，`PUBLIC_PATHS` 仅 `/api/health`；`QF_WIRE_API_TOKEN` + Bearer 放行非回环；`QF_WIRE_API_REQUIRE_TOKEN` 强制本机也鉴权；`QF_WIRE_ALLOW_PRIVATE_NETWORK` 显式开放私网 | `tests/unit/test_web_guard.py`、`tests/integration/test_dashboard_api.py` |
| R5.2 写操作收口 | 仅 `/api/settings`、`/api/digest/run` 两个 POST，`_guard_write` 顺序为：回环 → `X-Wire-Request: 1` → 请求身份 → `_guard_write_token`；写令牌由服务端启动时生成（或 `QF_WIRE_WRITE_TOKEN` 固定）并注入页面 `window.QF_WRITE_TOKEN`，跨站无法读取页面也伪造不了自定义头 | `tests/unit/test_web_guard.py`、`tests/integration/test_dashboard_api.py` |
| R5.2 CORS 可控 | `QF_WIRE_CORS_ORIGINS` 逗号分隔白名单；`OPTIONS` 预检与响应头同源判断；默认关闭 | `tests/unit/test_web_guard.py`（允许/拒绝/响应头） |
| R5.3 多用户隔离 | `config/loader.py`：`resolve_user` 校验 `^[A-Za-z0-9_-]{1,64}$`；`resolve_paths` 产出 `<data>/users/<id>/{config/,wire.db,archive/,data.js,api.token}`；CLI 用 `--user` / `QF_WIRE_USER` | `tests/unit/config/test_multiuser.py`（8 例，含 `../`、`a/b`、`..`、中文、超长 id） |
| R5.3 身份与选择分离 | `web/server.py:_authorize_user`：`qfw serve --user alice` 是**绑定实例**，请求头只能为空或 `alice`，其他 → 403；未绑定用户的多用户实例必须带 `X-QF-User-Token`，与 `<data>/users/<id>/api.token` 常数时间比较，缺失/错误统一 401（不泄露用户是否存在）；`qfw token --user <id>` 生成与轮换凭据 | `test_bound_instance_rejects_switching_user`、`test_shared_instance_requires_target_user_token`、`tests/unit/cli/test_token.py` |
| R5.3 配置损坏不串用户 | `web/server.py:_reload_config` 在多用户模式或显式用户下直接抛错，不再回落到启动时配置 | `test_multiuser_requires_user_header` |
| R5.3 用户配置完整性 | 用户目录 `config/` 三件套齐全才生效，否则回落全局配置 | `tests/unit/config/test_multiuser.py` |
| R5.4 内置调度 | `core/jobs.py`：`parse_schedule` 校验时区、5 段 cron、命令白名单（`run` / `digest` / `sources validate`）、重复 id、`options` 类型；`build_scheduler` 支持 Blocking/Background 两种调度器 | `tests/unit/core/test_jobs.py` |
| R5.4 CLI 入口 | `cli/schedule.py`：`qfw schedule`、`--once`、`--dry-run`；`qfw serve --with-scheduler` 同进程运行看板与调度 | `tests/unit/cli/test_schedule.py` |
| R5.4 日志落盘 | `logging/setup.py`：`QF_WIRE_LOG_FILE` 启用 `RotatingFileHandler`（5MB × 3），写失败只告警不影响主流程 | 调度/服务运行日志；`tests/unit/cli/test_schedule.py` |
| 部署文档与样例 | `.env.example` 补齐 token / CORS / 多用户 / 日志 / 调度变量；`docs/DEPLOYMENT.md`、`docs/CONFIG.md`、`README.md`、`docs/REQUIREMENTS_TRACEABILITY.md` 同步 | 文档内命令与实际路由逐条核对 |

## 关键行为

- 读接口：`/api/digest`、`/api/sources`、`/api/history`、`/api/events`、`/api/event?id=`、`/api/settings`、`/api/digest/job`；`/api/health` 始终公开。
- 写接口：`POST /api/settings`、`POST /api/digest/run`，需同时满足回环地址、`X-Wire-Request: 1`、请求身份校验、`X-QF-Write-Token` 四项。
- 写令牌在进程启动时用 `secrets.token_urlsafe(32)` 生成（`QF_WIRE_WRITE_TOKEN` 可固定），只注入页面 `window.QF_WRITE_TOKEN`，不写日志、不落盘。
- 非回环请求在未配置 token 时返回 403；配置 token 后缺少/错误 Bearer 返回 401。
- `Host` 头不属于 `127.0.0.1` / `localhost` / `[::1]` / 绑定地址时返回 403；监听 `0.0.0.0` / `::` 时不校验。
- 多用户请求缺少 `X-QF-User` 返回 400，非法 id 返回 400，不会创建目录；绑定实例收到其他用户 → 403，共享实例缺少/错误 `X-QF-User-Token` → 401。
- 调度器单任务 `max_instances=1`、`coalesce=true`、`misfire_grace_time=3600`，避免重复堆叠。
- `schedule.enabled=false` 时 `qfw schedule` 返回配置错误（退出码 3）；`qfw serve --with-scheduler` 只提示不启动调度。

## 测试

- 全量：`258 passed`（本机 Python 3.14.6，`PYTHONPATH="../deps;src"`）。
- 新增覆盖：
  - `tests/unit/test_web_guard.py`：回环/公网/私网、健康检查豁免、token 必填与本机绕过、Bearer 大小写、CORS 解析、绑定实例拒绝他人、共享实例校验 `X-QF-User-Token`、写令牌（缺失/正确/环境变量覆盖）、`Host` 头拒绝与放行。
  - `tests/unit/cli/test_token.py`：创建/复用/轮换、非法 id 与缺 `--user` 退出码 2、不产生越界目录。
  - `tests/unit/config/test_multiuser.py`：开关关闭忽略用户、每用户数据目录、环境变量用户、缺失用户、非法 id、完整/不完整用户配置、归档与 data.js 归属。
  - `tests/unit/core/test_jobs.py`：解析归一化与默认值、8 组非法配置、调度器注册、处理器分发、异常捕获、无数据提炼报错。
  - `tests/unit/cli/test_schedule.py`：dry-run JSON、关闭时退出码、`--once` 分发、部分失败、坏 cron。
  - `tests/integration/test_dashboard_api.py`：强制 token 401/200、本机绕过、CORS 预检允许/拒绝与响应头、多用户 `data.js` 隔离、路径穿越与缺失用户头 400、跨用户 403、目标用户凭据 401/200、写令牌缺失 403、页面注入令牌、伪造 `Host` 403。

## 风险与后续

1. Compose 场景下 `./config` 挂载到 `/app/config`，`./data` 挂载到 `/data`；页面写入的 `.env.local` 位于 `/data`，重建容器不丢，但换机器需自行备份。
2. 身份不来自客户端自称：绑定实例（`qfw serve --user <id>`）只服务该用户；需要一进程多用户时，必须为每个用户执行 `qfw token --user <id>` 并把 `api.token` 交给对应使用者，客户端带 `X-QF-User` + `X-QF-User-Token`。Wire 不做登录，直接暴露公网仍需反向代理层完成身份注入与 TLS。
3. 写令牌随进程重启变化；如果外部脚本要调写接口，用 `QF_WIRE_WRITE_TOKEN` 固定，否则每次重启都要从页面取新值。
4. 调度进程与看板共用同一 SQLite 文件，SQLite 已开启 WAL；若未来多进程同时写，需要改为单写进程或外部队列。
5. 日志文件轮转只在进程内生效；容器场景依赖 `./data` 持久化与外部日志采集。
6. 只读 API 的 token 是静态 Bearer，尚未做过期与轮换；公网暴露前需补齐。用户级 `api.token` 也只能靠 `qfw token --rotate` 手动轮换。
