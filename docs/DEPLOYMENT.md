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
- 需要跑定时采集时，额外启用 `scheduler` profile（或交给宿主 cron 调用 `docker compose exec wire qfw run`）。

停止与清理：

```bash
docker compose down          # 保留 data/
docker compose down -v       # 连卷一起删，数据不可恢复
```

## 只读 API

`qfw serve` 同时提供只读 JSON 接口，默认仅本机可访问：

| 接口 | 说明 |
|---|---|
| `GET /api/health` | 存活探测 |
| `GET /api/digest?topic=semiconductor&date=2026-10-22` | 赛道要点 |
| `GET /api/events?keyword=光刻&window=7d` | 事件检索 |
| `GET /api/events/<event_id>` | 事件时间线 |
| `GET /api/sources?topic=...` | 信源与评分 |
| `GET /api/status` | 最近一次运行状态与降级源 |

鉴权：

- 未设置 `QF_WIRE_API_TOKEN` 时，只允许来自回环地址的请求（校验 socket 对端地址，不信任 `X-Forwarded-For`）。
- 设置 `QF_WIRE_API_TOKEN` 后，非回环请求必须带 `Authorization: Bearer <token>`；回环请求可免鉴权（本地开发便利），可用 `QF_WIRE_API_REQUIRE_TOKEN=1` 强制全部鉴权。
- 写操作接口一律不提供。API 是只读的，采集只能通过 CLI 或调度器触发。

## 多用户隔离

`QF_WIRE_MULTIUSER=true` 时按用户目录隔离：

```
/data/users/<user_id>/
├── config/        # 该用户自己的 topics/sources/digest
├── wire.db
├── archive/
└── data.js
```

- 通过请求头 `X-QF-User`（API）或 `--user <id>`（CLI）选择上下文；缺失且多用户开启时报错，不猜测默认用户。
- 用户 id 只允许 `[a-zA-Z0-9_-]{1,64}`，防止路径穿越。
- 用户之间不共享 SQLite、不共享归档目录；`sources.yaml` 可共享只读基线，再叠加用户覆盖。
- 不引入云端账户体系：身份来自宿主环境（系统用户名、反向代理注入的可信头），Wire 自己不做登录。

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
    command: sources_validate
```

`qfw serve --with-scheduler` 启动时加载；`qfw run` 自身不触发调度。

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
- `config/` 与 `.env` 在 `.gitignore` 中；用户配置里禁止出现明文密钥，密钥一律走环境变量引用。
