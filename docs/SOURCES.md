# 信源清单与新增指南

## 当前清单

共 12 个赛道、106 个信源，统一定义在 `config/sources.yaml`。

| 赛道 id | 名称 | 源数 |
| --- | --- | --- |
| ai | AI / 大模型 | 16 |
| semiconductor | 半导体 / 芯片 | 9 |
| robotics | 机器人 / 自动化 | 5 |
| automotive | 汽车 / 新能源车 | 5 |
| energy | 能源 / 新能源 | 9 |
| biotech | 生物医药 / 健康 | 7 |
| aerospace | 航天 / 太空 | 6 |
| cybersecurity | 网络安全 | 5 |
| tech | 科技 / 互联网 | 16 |
| consumer | 消费电子 / 数码 | 7 |
| macro | 财经 / 宏观 | 13 |
| science | 科学 / 前沿 | 8 |

查看：`qfw sources list`。

## 新增 RSS 源

1. 在 `config/sources.yaml` 追加：

```yaml
  - id: example_tech
    name: Example Tech
    topic: tech
    type: rss
    url: https://example.com/feed.xml
    timeout_sec: 15
    retries: 2
    weight: 1.0
    enabled: true
```

2. 把 `example_tech` 加入 `config/topics.yaml` 对应赛道的 `sources`；
3. 运行 `qfw sources validate` 确认可访问、可解析；
4. 运行 `qfw run --topic tech --sources-only` 抽查条目。

## 非 RSS 源

`type: html` 与 `type: api` 需要在 `src/qf_wire/sources/` 提供适配器，并在 `registry.py` 注册。适配器实现 `SourceAdapter.fetch()`，返回统一的 `SourceItem`。

## 信源评分

`core/scorer.py` 基于历史记录计算：

- **准确率**：被多源交叉验证的比例；
- **时效性**：发布到采集的延迟分布；
- **重复率**：与其他源内容重复的比例。

综合分写入 SQLite，并作为提炼排序的权重。看板在每个要点旁展示信源可信度标记，`qfw sources list --output table` 可查看。

## 批量校验

```bash
qfw sources validate
python scripts/check_sources.py --concurrency 20
```

校验失败不会修改配置，只输出原因（超时 / 4xx / 5xx / 解析失败 / 空数据）。
