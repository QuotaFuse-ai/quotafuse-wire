# 0001 采集并发模型：asyncio + aiohttp 单会话全局限流

- 状态：已采纳（M2）
- 日期：2026-10-22
- 相关：`src/qf_wire/pipeline/fetch.py`

## 背景

M1 的串行采集在 106 个源上需要数分钟，无法支撑每日定时运行；需求要求“100+ 源秒级完成”，同时保留每源独立超时、重试与降级。

## 决策

1. 使用 `asyncio` + `aiohttp`，在一次 `asyncio.run` 中 `gather` 全部信源任务；
2. 全局只创建一个 `ClientSession` 和一个 `TCPConnector`，用 `asyncio.Semaphore` 控制总并发；
3. 连接池 `limit=并发度`、`limit_per_host=4`，避免对单一站点过度请求；
4. 并发度解析顺序：显式参数 > `QF_WIRE_FETCH_CONCURRENCY` > 默认 24，范围裁剪到 1..64；
5. 每个源使用 `ClientTimeout(total=timeout_sec)`，失败按 `min(0.2 * attempt, 1.0)` 秒退避重试；
6. 适配器只负责 `parse(bytes)`，网络层统一由 fetch 管道实现；同步 `fetch()` 仅保留给兼容入口与单源探测。

## 理由

- 单会话复用连接，避免 106 次 TLS 握手；`limit_per_host=4` 在提速与礼貌抓取之间取平衡；
- 并发度设上限 64，防止误配导致本机文件句柄或目标站点压力失控；
- 保持“单源失败不中断全局”：每个任务内部兜底并返回 `FetchResult(status="unavailable")`。

## 被否方案

| 方案 | 否因 |
| --- | --- |
| 线程池 + `urllib` | 100+ 线程上下文切换与内存开销大，连接无法复用 |
| Scrapy / Celery / 消息队列 | 引入常驻进程与中间件，违背本地优先、零托管依赖约束 |
| 无上限 `gather` | 106 个并发连接会被目标站点限流，且本机资源不可控 |

## 代价与风险

- 运行环境必须有 `aiohttp`（已在 `pyproject.toml` 声明）；M1 的标准库路径不再作为采集主路径；
- `limit_per_host=4` 意味着同域名的多个源仍会排队；真实源分布在大量不同站点，实测影响可忽略；
- 重试会放大慢源占用，但因单源超时独立，不会拖垮整轮采集。
