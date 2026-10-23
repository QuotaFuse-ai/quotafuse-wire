# QUOT-42 / M4 产品化：实现报告

- 日期：2026-10-23
- 分支：`agent/QUOT-42-m4`
- 关联规格：[`docs/DEPLOYMENT.md`](../../DEPLOYMENT.md)、[`docs/CONFIG.md`](../../CONFIG.md)
- 决策记录：[0005 多用户目录与 API 鉴权默认值](../../decisions/0005-multiuser-and-api-auth.md)、[0006 容器发布面与调度重试策略](../../decisions/0006-docker-loopback-and-scheduler-retry.md)、[0007 请求身份绑定与写令牌](../../decisions/0007-request-identity-binding.md)（0007 取代 0005 第 3、8 条）

## 交付对照

| 需求 | 落地 | 验证 |
| --- | --- | --- |
| R5.1 Docker Compose 一键部署 | `docker-compose.yml`、`Dockerfile`、`.dockerignore`：`docker compose up -d` 启动 `qfw serve --with-scheduler`，`./data` / `./config` 挂载，端口只映射到宿主机回环 | `tests/unit/test_compose_config.py`（静态校验）；`docs/DEPLOYMENT.md` 部署步骤 |
| R5.1 镜像不含用户数据 | `.dockerignore` 排除 `data/`、`.env*`、`*.db`；`Dockerfile` 只复制代码与默认配置模板 | `test_dockerfile_does_not_copy_user_data_or_old_mcp_port`、`test_dockerignore_excludes_secrets_and_data` |
| R5.1 健康检查 | compose healthcheck 调 `/api/health`，容器内存在 `QF_WIRE_API_TOKEN` 时自动附 Bearer | `test_compose_healthcheck_hits_health_endpoint` |
| R5.2 只读 API 默认仅本机 | `web/server.py`：`_guard_host` 校验 `Host` 头防 DNS rebinding，`_guard_read` 校验 socket 对端地址，`PUBLIC_PATHS` 仅 `/api/health`；`QF_WIRE_API_TOKEN` + Bearer 放行非回环；`QF_WIRE_API_REQUIRE_TOKEN` 强制本机也鉴权；`QF_WIRE_ALLOW_PRIVATE_NETWORK` 显式开放私网 | `tests/unit/test_web_guard.py`、`tests/integration/test_dashboard_api.py` |
| R5.2 只读接口补全 | `GET /api/health`、`/api/digest`、`/api/sources`、`/api/history`、`/api/status`、`/api/events?keyword=&window=`、`/api/events/<event_id>`、`/api/event?id=`、`/api/settings`、`/api/digest/job` | `test_events_keyword_and_window`、`test_event_detail_by_path` |
| R5.2 错误不泄露路径与密钥 | `web/server.py:_redact`：已配置 token / API Key 替换为 `***`，绝对路径替换为 `<path>`；未预期异常统一 `服务器内部错误` | `test_error_redaction_hides_paths_and_secrets`、`test_multiuser_config_error_does_not_leak_paths` |
| R5.2 写操作收口 | 仅 `/api/settings`、`/api/digest/run` 两个 POST，`_guard_write` 顺序为：回环 → `X-Wire-Request: 1` → 请求身份 → `_guard_write_token`；写令牌由服务端启动时生成（或 `QF_WIRE_WRITE_TOKEN` 固定）并注入页面 `window.QF_WRITE_TOKEN`，跨站无法读取页面也伪造不了自定义头 | `tests/unit/test_web_guard.py`、`tests/integration/test_dashboard_api.py` |
| R5.2 CORS 可控 | `QF_WIRE_CORS_ORIGINS` 逗号分隔白名单；`OPTIONS` 预检与响应头同源判断；默认关闭 | `tests/unit/test_web_guard.py`（允许/拒绝/响应头） |
| R5.3 多用户隔离 | `config/loader.py`：`resolve_user` 校验 `^[A-Za-z0-9_-]{1,64}$`；`resolve_paths` 产出 `<data>/users/<id>/{config/,wire.db,archive/,data.js,api.token}`；`web/server.py` 读 `X-QF-User`，CLI 用 `--user` / `QF_WIRE_USER` | `tests/unit/config/test_multiuser.py`（8 例，含 `../`、`a/b`、`..`、中文、超长 id） |
| R5.3 跨用户不可读 | 每用户独立 `wire.db`；事件详情与状态接口只查当前用户库 | `test_multiuser_db_isolation`（alice/bob 互查 404，`/api/status` 各返回自己的 runId） |
| R5.3 身份与选择分离 | `web/server.py:_authorize_user`：`qfw serve --user alice` 是**绑定实例**，请求头只能为空或 `alice`，其他 → 403；未绑定用户的多用户实例必须带 `X-QF-User-Token`，与 `<data>/users/<id>/api.token` 常数时间比较，缺失/错误统一 401（不泄露用户是否存在）；`qfw token --user <id>` 生成与轮换凭据 | `test_bound_instance_rejects_switching_user`、`test_shared_instance_requires_target_user_token`、`tests/unit/cli/test_token.py` |
| R5.3 配置损坏不串用户 | `web/server.py:_reload_config` 在多用户模式或显式用户下直接抛错，不再回落到启动时配置 | `test_multiuser_requires_user_header` |
| R5.3 用户配置完整性 | 用户目录 `config/` 四件套（topics/sources/digest/schedule）齐全才生效，否则回落全局配置 | `tests/unit/config/test_multiuser.py` |
| R5.4 内置调度 | `core/jobs.py`：`parse_schedule` 校验时区、5 段 cron、命令白名单（`run` / `digest` / `sources validate`）、重复 id、`options` 类型；`build_scheduler` 支持 Blocking/Background 两种调度器 | `tests/unit/core/test_jobs.py` |
| R5.4 失败重试 | `execute_job`：瞬时异常按 `options.retries` 重试（默认 1 次，上限 5），`retry_delay` 默认 5 秒；`WireError` 不重试 | `test_execute_job_retries_transient_errors`、`test_execute_job_gives_up_after_retries`、`test_execute_job_does_not_retry_config_errors` |
| R5.4 定时触发可用 | 注册后的 job 到点执行 | `test_scheduler_triggers_registered_job`（立即改写 `next_run_time` 触发） |
| R5.4 CLI 入口 | `cli/schedule.py`：`qfw schedule`、`--once`、`--dry-run`；`qfw serve --with-scheduler` 同进程运行看板与调度 | `tests/unit/cli/test_schedule.py` |
| R5.4 日志落盘 | `logging/setup.py`：`QF_WIRE_LOG_FILE` 启用 `RotatingFileHandler`（5MB × 3），写失败只告警不影响主流程 | 调度/服务运行日志；`tests/unit/cli/test_schedule.py` |
| R5.5 运维状态 | `GET /api/status`：上次运行、信源日、逐源状态、降级列表、归档天数；冷启动返回空结构 | `test_status_cold_start`、`test_status_reports_last_run_and_degraded` |
| 部署文档与样例 | `.env.example` 补齐 token / CORS / 多用户 / 日志 / 调度变量；`docs/DEPLOYMENT.md`、`docs/CONFIG.md`、`README.md`、`docs/REQUIREMENTS_TRACEABILITY.md` 同步 | 文档内命令与实际路由逐条核对 |

## 关键行为

- 读接口：`/api/digest`、`/api/sources`、`/api/history`、`/api/status`、`/api/events`、`/api/events/<id>`、`/api/event?id=`、`/api/settings`、`/api/digest/job`；`/api/health` 默认公开，强制鉴权时同样要求 token。
- 写接口：`POST /api/settings`、`POST /api/digest/run`，需同时满足回环地址、`X-Wire-Request: 1`、请求身份校验、`X-QF-Write-Token` 四项。
- 写令牌在进程启动时用 `secrets.token_urlsafe(32)` 生成（`QF_WIRE_WRITE_TOKEN` 可固定），只注入页面 `window.QF_WRITE_TOKEN`，不写日志、不落盘。
- 非回环请求在未配置 token 时返回 403；配置 token 后缺少/错误 Bearer 返回 401。
- `Host` 头不属于 `127.0.0.1` / `localhost` / `[::1]` / 绑定地址时返回 403；监听 `0.0.0.0` / `::` 时不校验。
- 多用户请求缺少 `X-QF-User` 返回 400，非法 id 返回 400，不会创建目录；绑定实例收到其他用户 → 403，共享实例缺少/错误 `X-QF-User-Token` → 401。
- `/api/events?window=` 支持 `1d` / `7d` / `12h` 等，非法窗口返回 400 且提示字段名。
- 调度器单任务 `max_instances=1`、`coalesce=true`、`misfire_grace_time=3600`，避免重复堆叠。
- `schedule.enabled=false` 时 `qfw schedule` 返回配置错误（退出码 3）；`qfw serve --with-scheduler` 只提示不启动调度。
- compose 只发布 `127.0.0.1:8790`，容器只跑看板；MCP 8791 按需在宿主机启动。

## 测试

- 全量：`0 passed`（合入安全分支后统计，本机 Python 3.14.6，`PYTHONPATH="../deps;src"`）。
- 新增覆盖：
  - `tests/unit/test_web_guard.py`：回环/公网/私网、健康检查豁免、token 必填与本机绕过、Bearer 大小写、CORS 解析、错误脱敏、绑定实例拒绝他人、共享实例校验 `X-QF-User-Token`、写令牌（缺失/正确/环境变量覆盖）、`Host` 头拒绝与放行。
  - `tests/unit/cli/test_token.py`：创建/复用/轮换、非法 id 与缺 `--user` 退出码 2、不产生越界目录。
  - `tests/unit/config/test_multiuser.py`：开关关闭忽略用户、每用户数据目录、环境变量用户、缺失用户、非法 id、完整/不完整用户配置、归档与 data.js 归属。
  - `tests/unit/core/test_jobs.py`：解析归一化与默认值、8 组非法配置、调度器注册与即时触发、处理器分发、瞬时异常重试、重试耗尽、配置错误不重试、无数据提炼报错。
  - `tests/unit/cli/test_schedule.py`：dry-run JSON、关闭时退出码、`--once` 分发、部分失败、坏 cron。
  - `tests/integration/test_dashboard_api.py`：强制 token 401/200、本机绕过、CORS 预检允许/拒绝与响应头、多用户 `data.js` 与 `wire.db` 隔离、跨用户 404、路径穿越与缺失用户头 400、目标用户凭据 401/200、写令牌缺失 403、页面注入令牌、伪造 `Host` 403、`/api/status` 冷启动与降级、事件关键词/窗口查询、路径式事件详情、错误脱敏。
  - `tests/unit/test_compose_config.py`：compose 端口仅回环、调度命令与容器配置目录、healthcheck、卷挂载、Dockerfile 不复制用户数据、`.dockerignore` 排除密钥与数据。

## 风险与后续

1. Compose 场景下 `./config` 挂载到 `/app/config`，`./data` 挂载到 `/data`；页面写入的 `.env.local` 位于 `/data`，重建容器不丢，但换机器需自行备份。
2. 身份不来自客户端自称：绑定实例（`qfw serve --user <id>`）只服务该用户；需要一进程多用户时，必须为每个用户执行 `qfw token --user <id>` 并把 `api.token` 交给对应使用者，客户端带 `X-QF-User` + `X-QF-User-Token`。Wire 不做登录，直接暴露公网仍需反向代理层完成身份注入与 TLS。
3. 写令牌随进程重启变化；如果外部脚本要调写接口，用 `QF_WIRE_WRITE_TOKEN` 固定，否则每次重启都要从页面取新值。
4. 调度进程与看板共用同一 SQLite 文件，SQLite 已开启 WAL；若未来多进程同时写，需要改为单写进程或外部队列。
5. 日志文件轮转只在进程内生效；容器场景依赖 `./data` 持久化与外部日志采集。
6. 只读 API 的 token 是静态 Bearer，尚未做过期与轮换；公网暴露前需补齐。用户级 `api.token` 也只能靠 `qfw token --rotate` 手动轮换。
7. **本机无 Docker 与 `gh` CLI**：本轮 Docker 部分以 `docker compose config` 等价的静态测试（`tests/unit/test_compose_config.py`）与本地干净目录启动模拟验证，未实际构建镜像。
