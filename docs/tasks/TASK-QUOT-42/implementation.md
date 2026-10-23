# QUOT-42 / M4 产品化：实现报告

- 日期：2026-10-23
- 分支：`agent/QUOT-39-dashboard`
- 关联规格：[`docs/DEPLOYMENT.md`](../../DEPLOYMENT.md)、[`docs/CONFIG.md`](../../CONFIG.md)
- 决策记录：[0005 多用户目录与 API 鉴权默认值](../../decisions/0005-multiuser-and-api-auth.md)

## 交付对照

| 需求 | 落地 | 验证 |
| --- | --- | --- |
| R5.1 Docker Compose 一键部署 | `docker-compose.yml`、`Dockerfile`：`docker compose up -d` 启动 `qfw serve --with-scheduler`，`./data` / `./config` 挂载，端口只映射到宿主机回环 | `docs/DEPLOYMENT.md` 部署步骤；`/api/health` 存活探测 |
| R5.2 只读 API 默认仅本机 | `web/server.py`：`_guard_read` 校验 socket 对端地址，`PUBLIC_PATHS` 仅 `/api/health`；`QF_WIRE_API_TOKEN` + Bearer 放行非回环；`QF_WIRE_API_REQUIRE_TOKEN` 强制本机也鉴权；`QF_WIRE_ALLOW_PRIVATE_NETWORK` 显式开放私网 | `tests/unit/test_web_guard.py`、`tests/integration/test_dashboard_api.py` |
| R5.2 写操作收口 | 仅 `/api/settings`、`/api/digest/run` 两个 POST，要求回环 + `X-Wire-Request: 1`；浏览器跨站无法伪造该头 | `tests/integration/test_dashboard_api.py` |
| R5.2 CORS 可控 | `QF_WIRE_CORS_ORIGINS` 逗号分隔白名单；`OPTIONS` 预检与响应头同源判断；默认关闭 | `tests/unit/test_web_guard.py`（允许/拒绝/响应头） |
| R5.3 多用户隔离 | `config/loader.py`：`resolve_user` 校验 `^[A-Za-z0-9_-]{1,64}$`；`resolve_paths` 产出 `<data>/users/<id>/{config/,wire.db,archive/,data.js}`；`web/server.py` 读 `X-QF-User`，CLI 用 `--user` / `QF_WIRE_USER` | `tests/unit/config/test_multiuser.py`（8 例，含 `../`、`a/b`、`..`、中文、超长 id） |
| R5.3 配置损坏不串用户 | `web/server.py:_reload_config` 在多用户模式或显式用户下直接抛错，不再回落到启动时配置 | `test_multiuser_requires_user_header` |
| R5.3 用户配置完整性 | 用户目录 `config/` 三件套齐全才生效，否则回落全局配置 | `tests/unit/config/test_multiuser.py` |
| R5.4 内置调度 | `core/jobs.py`：`parse_schedule` 校验时区、5 段 cron、命令白名单（`run` / `digest` / `sources validate`）、重复 id、`options` 类型；`build_scheduler` 支持 Blocking/Background 两种调度器 | `tests/unit/core/test_jobs.py` |
| R5.4 CLI 入口 | `cli/schedule.py`：`qfw schedule`、`--once`、`--dry-run`；`qfw serve --with-scheduler` 同进程运行看板与调度 | `tests/unit/cli/test_schedule.py` |
| R5.4 日志落盘 | `logging/setup.py`：`QF_WIRE_LOG_FILE` 启用 `RotatingFileHandler`（5MB × 3），写失败只告警不影响主流程 | 调度/服务运行日志；`tests/unit/cli/test_schedule.py` |
| 部署文档与样例 | `.env.example` 补齐 token / CORS / 多用户 / 日志 / 调度变量；`docs/DEPLOYMENT.md`、`docs/CONFIG.md`、`README.md`、`docs/REQUIREMENTS_TRACEABILITY.md` 同步 | 文档内命令与实际路由逐条核对 |

## 关键行为

- 读接口：`/api/digest`、`/api/sources`、`/api/history`、`/api/events`、`/api/event?id=`、`/api/settings`、`/api/digest/job`；`/api/health` 始终公开。
- 写接口：`POST /api/settings`、`POST /api/digest/run`，只接受回环请求并带 `X-Wire-Request: 1`。
- 非回环请求在未配置 token 时返回 403；配置 token 后缺少/错误 Bearer 返回 401。
- 多用户请求缺少 `X-QF-User` 返回 400，非法 id 返回 400，不会创建目录。
- 调度器单任务 `max_instances=1`、`coalesce=true`、`misfire_grace_time=3600`，避免重复堆叠。
- `schedule.enabled=false` 时 `qfw schedule` 返回配置错误（退出码 3）；`qfw serve --with-scheduler` 只提示不启动调度。

## 测试

- 全量：`231 passed`（本机 Python 3.14.6，`PYTHONPATH="../deps;src"`）。
- 新增覆盖：
  - `tests/unit/test_web_guard.py`：回环/公网/私网、健康检查豁免、token 必填与本机绕过、Bearer 大小写、CORS 解析。
  - `tests/unit/config/test_multiuser.py`：开关关闭忽略用户、每用户数据目录、环境变量用户、缺失用户、非法 id、完整/不完整用户配置、归档与 data.js 归属。
  - `tests/unit/core/test_jobs.py`：解析归一化与默认值、8 组非法配置、调度器注册、处理器分发、异常捕获、无数据提炼报错。
  - `tests/unit/cli/test_schedule.py`：dry-run JSON、关闭时退出码、`--once` 分发、部分失败、坏 cron。
  - `tests/integration/test_dashboard_api.py`：强制 token 401/200、本机绕过、CORS 预检允许/拒绝与响应头、多用户 `data.js` 隔离、路径穿越与缺失用户头 400。

## 风险与后续

1. Compose 场景下 `./config` 挂载到 `/app/config`，`./data` 挂载到 `/data`；页面写入的 `.env.local` 位于 `/data`，重建容器不丢，但换机器需自行备份。
2. 多用户身份来自宿主环境（`X-QF-User` / `--user`），Wire 不做登录；若直接暴露到公网，必须在反向代理层完成身份注入与 TLS。
3. 调度进程与看板共用同一 SQLite 文件，SQLite 已开启 WAL；若未来多进程同时写，需要改为单写进程或外部队列。
4. 日志文件轮转只在进程内生效；容器场景依赖 `./data` 持久化与外部日志采集。
5. 只读 API 的 token 是静态 Bearer，尚未做过期与轮换；公网暴露前需补齐。
