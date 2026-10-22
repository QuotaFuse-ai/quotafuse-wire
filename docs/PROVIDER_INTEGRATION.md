# 与 Council / StockData 对接

Wire 在生态里的角色是**资讯 Provider**。它不实现行情、财报、资金流，也不做分析决策；它把多源资讯整理成统一的 `WireEnvelope`，交给 Council 的分析师消费。

- [职责边界](#职责边界)
- [WireEnvelope ↔ DataEnvelope](#wireenvelope--dataenvelope)
- [WireProvider 接口](#wireprovider-接口)
- [注册进 Council DataAccessLayer](#注册进-council-dataaccesslayer)
- [模型网关复用](#模型网关复用)
- [与生态资讯模块对齐](#与生态资讯模块对齐)
- [联调清单](#联调清单)

## 职责边界

| 能力 | Wire | StockData | Council |
|---|---|---|---|
| 新闻、政策、产业链资讯采集 | ✅ | ❌ | ❌ |
| 事件聚类、时间线、信源评分 | ✅ | ❌ | ❌ |
| 行情、财报、公告、资金、风险事件 | ❌ | ✅ | 消费 |
| 多角色分析、辩论、回测、告警 | ❌ | ❌ | ✅ |
| MCP 工具 | ✅ 资讯类 | ✅ 数据类 | ✅ 分析类 |

Wire 不重复实现行情和财报采集；Council 不重复实现资讯采集。

## WireEnvelope ↔ DataEnvelope

`WireEnvelope` 的字段是 `DataEnvelope` 的子集加资讯特化字段。映射规则：

| WireEnvelope | DataEnvelope | 说明 |
|---|---|---|
| `domain` | `domain` | 固定 `news` / `policy` / `industry`，与 Council 的 domain 枚举对齐 |
| `topic` | `scope.topic` | 赛道 id |
| `event_id` | `scope.event_id` | 事件维度可选 |
| `data_as_of` | `data_as_of` | 数据截止日期，用于新鲜度判断 |
| `payload` | `payload` | 结构化资讯正文 |
| `source` | `source` | 固定 `wire` |
| `source_detail` | `source_detail` | 原始信源列表，用于溯源 |
| `fetched_at` | `fetched_at` | 采集时间 |
| `freshness` | `freshness` | `realtime` / `cached` / `archive` |
| `confidence` | `confidence` | `high` / `medium` / `low` |
| `source_status` | `source_status` | `ok` / `degraded` / `partial` |

`freshness` 与 `confidence` 必须由 Wire 侧给出，不允许 Council 反推：只有 Wire 知道哪些源降级、哪些条目来自单一低权重源。

`provider/envelope.py` 提供双向转换：

```python
from qf_wire.provider.envelope import to_data_envelope, from_data_envelope

data_env = to_data_envelope(wire_env)      # 交给 Council
wire_env = from_data_envelope(data_env)    # 读取生态里其他 provider 的输出
```

## WireProvider 接口

`provider/wire_provider.py` 实现 Council 的 Provider 协议（同步 + 异步双入口，按 Council 当前协议版本实现其一即可，另一者做薄封装）：

```python
class WireProvider:
    name = "wire"
    domains = ("news", "policy", "industry")

    def get_digest(self, topic: str, date: date | None = None) -> WireEnvelope: ...
    def search_events(self, keyword: str, window: str = "7d", topic: str | None = None) -> WireEnvelope: ...
    def get_timeline(self, event_id: str) -> WireEnvelope: ...
    def list_sources(self, topic: str | None = None) -> WireEnvelope: ...
```

约束：

- 只读，所有方法不得触发采集；数据来自本地归档。
- 无数据时返回空 `payload` + `freshness = archive`，不抛异常（Council 侧按“无资讯”处理，不是错误）。
- 数据库路径由 `QF_WIRE_DATA_DIR` 决定，与 Council 进程通过文件系统共享，不引入网络依赖。
- 不 import Council 的包；协议通过鸭子类型 + `DataEnvelope` 字典契约对齐，避免双向依赖。

## 注册进 Council DataAccessLayer

```python
from qf_wire.provider.wire_provider import WireProvider

data_access.register(WireProvider())
```

注册后 Council 的新闻分析师、政策分析师通过 `data_access.get("wire", domain="news", topic="semiconductor")` 取数。Council 侧不需要知道 Wire 的信源细节，只需要 `source_detail` 与 `confidence` 做引用标注。

## 模型网关复用

`digest.yaml` 的 `provider` 支持 `claude-cli` / `api` / `gateway`：

```yaml
digest:
  provider: gateway
  default_model: user-model
  gateway:
    base_url: ${QF_WIRE_MODEL_GATEWAY_URL}
    api_key_env: QF_WIRE_MODEL_GATEWAY_KEY
```

- `gateway` 模式下请求走 StockData/Council 的统一 `model_gateway`，模型选择、重试、降级由网关负责。
- 仍然保留“用户自己的模型”原则：`default_model` 由用户填写，Wire 不内置任何托管模型或默认密钥。
- 网关不可用时降级为 `claude-cli`；两者都不可用时跳过提炼，只输出采集结果，并在 `source_status` 标 `partial`。

## 与生态资讯模块对齐

- **源清单**：`scripts/export_sources.py` 导出生态共享格式，供各项目同步。
- **赛道定义**：赛道 id 使用稳定英文 slug，`legacy_key` 保留旧中文键，跨项目引用一律用 slug。
- **提炼 prompt**：`prompts/` 使用统一的提炼规则（事实优先、多源合并、禁止交易建议），差异只允许出现在赛道特化段落。

## 联调清单

1. `qfw run --topic semiconductor` 产出一条归档记录；
2. `WireProvider().get_digest("semiconductor")` 拿到非空 `payload`；
3. `to_data_envelope()` 输出的字段能被 Council 的 `DataEnvelope` 校验通过；
4. Council 侧分析师能引用 `source_detail` 中的信源 id；
5. 源全部失败时，Wire 返回 `source_status = partial` 而不是抛异常。
