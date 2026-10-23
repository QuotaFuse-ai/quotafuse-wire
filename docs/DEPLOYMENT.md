# 部署

本地优先是硬约束：所有默认监听地址都是 `127.0.0.1`，不引入云端账户，不要求外网暴露。

- [端口规划](#端口规划)
- [本地运行](#本地运行)
- [Docker Compose](#docker-compose)
- [只读 API](#只读-api)
- [多用户隔离](#多用户隔离)
- [定时调度](#定时调度)
- [数据备份](#数据备份)
- [安全默认值](#安全默认值)

## 端口规划

| 服务 | 端口 | 默认监听 |
|---|---|---|
| Wire 看板 | 8790 | `127.0.0.1` |
| Wire MCP http | 8791 | `127.0.0.1` |
| Council | 8788 | 由 Council 决定 |
| StockData Admin | 8787 | 由 StockData 决定 |
| 旧版看板入口 | 8793 | `127.0.0.1` |

8790 / 8791 与 8787 / 8788 不冲突。8793 保留给旧版看板入口，便于迁移期并行对比。

## 本地运行

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e .

qfw config validate          # 校验 YAML
qfw sources validate         # 逐个探测源可用性
qfw run                      # 采集 + 提炼 + 归档 + 生成 data.js
qfw serve --port 8790        # 打开 http://127.0.0.1:8790
```

Python 要求 >= 3.10。若系统默认 `python` 过旧，用绝对路径指定解释器（Windows 上常见 `C:\Python311\python.exe` 或 `py -3.12`）。

## Docker Compose

```bash
cp .env.example .env
docker compose up -d
docker compose logs -f wire
```

- 端口映射写成 `127.0.0.1:8790:8790` / `127.0.0.1:8791:8791`，容器内监听 `0.0.0.0` 但宿主机只暴露本机。
- `./data` 挂载到 `/data`，`./config` 挂载到 `/app/config`，镜像里不带用户配置与数据。
- `docker-compose.yml` 不含任何密钥；模型密钥通过 `.env` 或宿主的 `claude` CLI 提供。
- 容器启动命令是 `qfw serve --with-scheduler`：看板与定时任务同进程。`config/schedule.yaml` 的 `enabled` 仍为 `false` 时只提供看板，日志里会说明本次未启动调度。
- 日志写到 `/data/logs/wire.log`（由 `QF_WIRE_LOG_FILE` 指定，5MB 轮转、保留 3 份），随 `./data` 保留。
- 启动后验证：`curl http://127.0.0.1:8790/api/health`。模型凭证可直接在页面「AI 与生成」里填写，写入 `/data/.env.local`（容器内路径），重建容器不丢。

停止与清理：

```bash
docker compose down          # 保留 data/
docker compose down -v       # 连卷一起删，数据不可恢复
```

## 只读 API

`qfw serve` 同时提供只读 JSON 接口，默认仅本机可访问：

| 接口 | 说明 |
|---|---|
| `GET /api/health` | 存活探测，任何来源都可访问 |
| `GET /api/digest?topic=semiconductor&date=2026-10-22` | 赛道要点 |
| `GET /api/sources?topic=...&date=...` | 信源状态与降级提示 |
| `GET /api/history?topic=...&days=7&date=...` | 最近 N 天的趋势 |
| `GET /api/events?topic=...&date=...` | 当日事件 |
| `GET /api/event?id=<event_id>` | 单条事件与时间线 |
| `GET /api/settings` | 页面可编辑的模型配置（密钥脱敏） |
| `GET /api/digest/job` | 提炼任务进度快照 |
| `POST /api/settings` | 保存模型配置（仅本机 + `X-Wire-Request: 1` + 写令牌） |
| `POST /api/digest/run` | 触发一次提炼（仅本机 + `X-Wire-Request: 1` + 写令牌） |

读接口默认只接受本机请求（校验 socket 对端地址，不信任 `X-Forwarded-For`）；写接口一律要求回环地址、`X-Wire-Request: 1` 和页面下发的一次性写令牌，不提供跨域写入。

鉴权：

- 未设置 `QF_WIRE_API_TOKEN` 时，只允许来自回环地址的请求；同一局域网的其他机器被拒绝。
- 设置 `QF_WIRE_API_TOKEN` 后，非回环请求必须带 `Authorization: Bearer <token>`；回环请求可免鉴权（本地开发便利），可用 `QF_WIRE_API_REQUIRE_TOKEN=1` 强制全部鉴权。
- 需要把只读 API 开放给内网其他机器时，除了设置 token，还要显式打开 `QF_WIRE_ALLOW_PRIVATE_NETWORK=1`；不设置时私网地址同样被拒绝。
- 写令牌在 `qfw serve` 启动时随机生成（32 字节），打开 `http://127.0.0.1:8790/` 时由服务端注入页面，页面里的请求自动带上 `X-QF-Write-Token`。需要固定值（例如脚本调用）时设置 `QF_WIRE_WRITE_TOKEN`，环境变量优先。该令牌只防“别的网页/本机其它程序误触发”，不是远程访问凭据。
- `Host` 头必须与监听地址一致（`127.0.0.1:<port>`、`localhost:<port>` 等），不一致直接 403，用于挡住 DNS rebinding。监听 `0.0.0.0` 时不做该限制。
- 跨域默认关闭，浏览器直连后端时才配置 `QF_WIRE_CORS_ORIGINS`（逗号分隔的完整 Origin）。
- 采集与提炼不会由只读接口隐式触发：`/api/digest/run` 只在本机页面点击时生效。

## 多用户隔离

`QF_WIRE_MULTIUSER=true` 时按用户目录隔离：

```
/data/users/<user_id>/
├── config/        # 该用户自己的 topics/sources/digest
├── wire.db
├── archive/
└── data.js
```

- 最省事的用法是**实例绑定用户**：`QF_WIRE_MULTIUSER=true qfw serve --user alice`。该看板只服务 alice，浏览器不需要额外请求头；任何 `X-QF-User` 指向其他用户都被 403 拒绝。
- 一个实例服务多个用户时（不带 `--user` 启动），`X-QF-User` 只负责**选择**用户，不能单独作为身份。请求必须同时带 `X-QF-User-Token`，其值等于该用户目录下的 `api.token`。用 `qfw token --user <id>` 生成（`--rotate` 轮换，旧值立即失效）：

  ```bash
  qfw token --user alice            # 首次生成并打印
  curl -H "X-QF-User: alice" -H "X-QF-User-Token: <token>" http://127.0.0.1:8790/data.js
  ```

- 用户 id 只允许 `[a-zA-Z0-9_-]{1,64}`，`../`、斜杠、空格、超长 id 全部拒绝。
- 每个用户的数据目录独立：`wire.db`、`archive/`、`data.js`、`api.token` 都不共享。用户目录下的 `config/` 只有 `topics.yaml`、`sources.yaml`、`digest.yaml` 三件套齐全时才生效，否则回落到全局配置。
- 配置损坏时多用户模式不会退回别人的配置，而是直接报错让调用方重新选择用户。
- 不引入云端账户体系：`api.token` 是本地凭据文件，不是登录账号；直接暴露到公网前，仍应由反向代理完成鉴权与 TLS。

## 定时调度

两种方式，二选一：

**内置 APScheduler**（`config/schedule.yaml`）：

```yaml
enabled: true
timezone: Asia/Shanghai
jobs:
  - id: daily_run
    cron: "0 7 * * *"
    command: run
    options: { topics: all }
  - id: weekly_source_check
    cron: "0 6 * * 1"
    command: sources validate
```

- `command` 只接受 `run`、`digest`、`sources validate`；`cron` 是标准 5 段表达式，按 `timezone` 解释。
- `qfw serve --with-scheduler`：看板与调度同进程，适合 Docker 与长期运行。
- `qfw schedule`：只跑调度（阻塞进程）；`--once` 立即执行全部启用任务后退出；`--dry-run` 只打印任务表，不执行。
- 调度日志默认写 stderr；设置 `QF_WIRE_LOG_FILE` 后同时写文件（5MB 轮转、保留 3 份）。
- `qfw run` 自身不触发调度。

**系统 cron**（推荐给 Docker 之外的场景）：

```cron
0 7 * * * cd /opt/quota-fuse-wire && .venv/bin/qfw run >> data/logs/run.log 2>&1
```

`qfw run` 的 stdout 是结构化结果、stderr 是日志，重定向时注意分开。

## 数据备份

- 需要备份的只有 `data/`：`wire.db`、`archive/`、`data.js`。
- `wire.db` 用 SQLite 的 `VACUUM INTO` 或 `.backup` 做一致性快照，不要直接复制正在写入的文件。
- `archive/` 是按日期的不可变文件，可直接增量同步。
- 归档有保留期（默认 365 天），过期清理只在 `qfw run` 末尾执行，可用 `QF_WIRE_ARCHIVE_RETENTION_DAYS` 调整。

## 安全默认值

- 默认监听 `127.0.0.1`，IPv4 与 IPv6 回环都要处理（`::1` 同样视为本机）。
- API 只读；跨域默认关闭，需要时显式配置 `QF_WIRE_CORS_ORIGINS`。
- 日志与错误输出脱敏：不打印 `Authorization`、`api_key`、完整 URL 查询串。
- 仓库中的 `.env` 只保留空值；含密钥的 `.env.local` 与 `config/*.local.yaml` 已被 `.gitignore` 忽略，用户配置里禁止出现明文密钥。
