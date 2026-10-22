# QUOT-40 / M2 采集与分析深度：实现报告

- 日期：2026-10-22
- 分支：`agent/QUOT-40-m2`
- 基线：M1 合并后的 `5dfea07`
- 关联规格：[`docs/specs/analysis-pipeline.md`](../../specs/analysis-pipeline.md)
- 决策记录：[0001 并发](../../decisions/0001-async-fetch-concurrency.md)、[0002 聚类](../../decisions/0002-event-clustering.md)、[0003 评分](../../decisions/0003-source-scoring.md)

## 交付对照

| 需求 | 落地 | 验证 |
| --- | --- | --- |
| R3.1 异步并发采集 | `pipeline/fetch.py`：单 `ClientSession` + 全局 `Semaphore` + `limit_per_host=4`，并发度 1..64 可配 | 本地 106 源夹具，21.38s → 1.03s（并发 24） |
| R3.2 事件聚类 | `core/cluster.py`：bigram 余弦 + SimHash + 实体冲突门控，稳定 `event_id` | `tests/unit/core/test_cluster.py`（5 同事件 + 2 无关） |
| R3.3 事件时间线 | `core/cluster.py:timeline`、`qfw event timeline` | CLI 测试 + 看板运行时验证 |
| R3.4 信源评分与迁移 | `core/scorer.py`、`storage/migrations/0002_source_scores.sql` | `tests/unit/core/test_scorer.py`（7 例） |
| R3.5 评分参与要点权重 | `scorer.apply_to_digest`，编排层在提炼后调用 | 降级用例断言 `medium/low` |
| R3.6 赛道级提炼策略 | `pipeline/digest.py` + `config/digest.yaml`（`prompt_file/model/output_schema`）；`user-model` 为占位符，不转发 `--model` | `tests/unit/pipeline/test_digest.py` |
| CLI 补齐 | `cli/event.py`（list/show/timeline）、`cli/history.py`（多源/事件增量）、CSV、退出码 6 | `tests/unit/cli/test_event.py`；README/架构/需求文档退出码表 |
| 看板增强 | `web/static/index.html.tpl` 多源折叠、时间线、评分徽标；`scheduler._render_from_store` 注入 `sourceStatus/sourceScores` | 8790 端口实跑（见下） |

## 实测：串行 vs 并发

条件：106 个本地 RSS 源，分布在 27 个端口（避免 `limit_per_host=4` 干扰），每请求固定 200ms，`retries=0`，每档重复 2 次取稳定值。

| 并发 | 第 1 次 | 第 2 次 | 结果 | 加速比 |
| --- | --- | --- | --- | --- |
| 1（串行基线） | 21.38s | 21.37s | 106/106 ok | 1.0x |
| 24（默认） | 1.03s | 1.03s | 106/106 ok | 20.8x |
| 32 | 0.84s | 0.85s | 106/106 ok | 25.3x |

理论串行下界 `106 × 0.2s = 21.2s`，与实测一致；真实网络单请求通常 0.5–1s，串行将达 1–2 分钟，默认并发可压到 3–6 秒级。

## 测试

- 全量：`88 passed in 8.82s`（本机 Python 3.12.10，离线夹具，无外网）。
- 新增：
  - `tests/unit/core/test_cluster.py`：5 条同事件标题折叠为一组、2 条无关标题独立；多源事件 `source_count=5`、`confidence=high`、时间线升序；`event_id` 重建稳定；实体冲突不合并；超出 7 天窗口不合并。
  - `tests/unit/core/test_scorer.py`：权重计算、冷启动中性分、印证/时效/独家单调性、跨运行累加、低分降级、`score_map`。
  - `tests/unit/pipeline/test_fetch.py`：并发度解析优先级与裁剪。
  - `tests/integration/test_fetch_concurrency.py`：104 快源 + 8 慢源 + 2 错误源，验证并发上限、超时/HTTP 错误标记、耗时阈值、无未关闭会话告警、线程回落。
  - `tests/unit/cli/test_event.py`、`tests/unit/pipeline/test_digest.py`：事件命令、CSV、退出码 6、赛道级 prompt/schema、占位模型不转发、API provider 缺模型时降级。

## 看板运行时验证（127.0.0.1:8790）

用临时库写入 1 个五源事件、1 个无关事件、3 个信源评分和 1 个不可用源后启动看板：

- `GET /` 200，返回内置页面；
- `GET /data.js` 200，同一 `event_id` 折叠为 5 条，全部 `source_count=5`；含 `sourceScores`、`sourceStatus`、`sourceNotice`；
- `GET /api/event?id=…` 200，时间线 5 条且按时间升序；
- `GET /api/events`、`/api/sources`、`/api/history`、`/api/digest`、`/api/health` 均 200。

## 风险与后续

1. 聚类阈值（0.56 / 0.86 / 0.30）与实体别名表基于规则，需用真实历史数据回归调参；
2. 评分中的“准确率”是被多源印证的代理指标，转载型错误仍会得分，M3 可引入纠错信号；
3. `limit_per_host=4` 会让同域名多源排队，若未来集中接入同站点需上调或按域名分组；
4. 提炼实测依赖本机 `claude-cli` 或用户 API key；仓库不内置 key，CI 只测解析与降级路径；
5. `gateway` provider 属于 M3，当前 `api`/`claude-cli` 已覆盖本地使用场景。

## 复现命令

```bash
# 采集（默认并发 24）
qfw run --sources-only
# 指定并发
qfw run --max-workers 32
# 事件与时间线
qfw event list --topic semiconductor
qfw event show <event_id>
qfw event timeline <event_id> --output csv
# 看板
qfw serve --port 8790
```
