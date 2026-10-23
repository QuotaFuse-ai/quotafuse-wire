# QUOT-43 缺陷修复复核

对应报告：[TEST_REPORT.md](TEST_REPORT.md)。按报告建议顺序修复，全部缺陷已在同一分支验证。

## 缺陷与修复

| 编号 | 缺陷 | 修复位置 | 处理方式 |
|---|---|---|---|
| P0-1 | wheel 缺少 migrations / schema / prompts / static，安装后报缺文件 | `pyproject.toml`、`src/qf_wire/schema/`、`src/qf_wire/prompts/`、`validator.py`、`loader.py` | 包内新增 `schema/`、`prompts/` 目录并纳入 `package-data`；`SCHEMA_DIR`、提示词定位改为包内路径，配置目录与仓库目录作为优先级更高的候选 |
| P1-1 | 同一 URL 出现在多个赛道时，后一赛道覆盖前一赛道的 `topic` / `event_id`，前一赛道时间线为空 | `src/qf_wire/storage/migrations/0003_items_topic_url.sql`、`sqlite.py`、`core/scheduler.py` | 唯一键由 `(day, url)` 改为 `(topic, day, url)`；写库 upsert 不再改写 `topic`；调度按赛道复制条目后再处理 |
| P1-2 | 干净目录下 `qfw config migrate` 被启动时的自动迁移抢跑，命令实际不可用 | `src/qf_wire/cli/main.py`、`src/qf_wire/cli/config.py` | `config` 子命令跳过自动迁移；迁移目标目录由路径解析直接得出，不再要求 `topics.yaml` 已存在 |
| P1-3 | 迁移生成的 `digest.yaml` 引用 `prompts/*.md`，但迁移过程不复制提示词，校验直接失败 | `src/qf_wire/config/migrate.py` | 迁移结束时把包内默认提示词补到配置同级 `prompts/`，已存在的文件不覆盖；dry-run 只打印计划 |
| P1-4 | 自带的 `digest.yaml` 含 `gateway` 段，schema 未声明，校验报未知字段 | `config/schema/digest.schema.json` | 补充 `gateway.base_url` / `gateway.api_key_env` 定义，并同步包内副本 |
| P2-1 | `/api/history` 非法 `date` 未捕获 `ValueError`，连接被直接断开 | `src/qf_wire/web/server.py` | 先校验参数再开库，非法日期返回 400「date 格式应为 YYYY-MM-DD」 |

## 验证

- 全量测试：`237 passed`，无 xfail；原先 4 个 xfail（3 个打包、1 个共用信源时间线）与 1 个 P2 用例全部转为通过。
- 新增回归用例：`tests/unit/cli/test_config_migrate.py`，覆盖干净配置目录下的迁移与随后校验。
- wheel 实测：构建产物包含 `qf_wire/storage/migrations/*.sql`（3）、`qf_wire/schema/*.schema.json`（3）、`qf_wire/prompts/*.md`（3）、`qf_wire/web/static/*`（1）。
- 安装态实测：把 wheel 解包到独立目录后，在无任何配置文件的目录执行 `config migrate` → `config validate`，退出码均为 0，提示词被正确落盘。

## 未覆盖项

- Docker 在本机不可用，Compose 相关项仍以文档与单元测试为准。
