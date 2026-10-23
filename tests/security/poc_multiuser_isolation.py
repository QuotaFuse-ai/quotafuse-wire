"""QUOT-44 PoC 4：X-QF-User 只是「选用户」，不是「认证用户」。

复现：
1. 多用户模式下，任意回环客户端只需带 X-QF-User 就能读任意用户的 data.js / wire.db。
2. 配置一个全局 QF_WIRE_API_TOKEN 后，同一个 token 仍可读取所有用户。
3. 对照：路径穿越、Unicode、超长 id 会被拒绝（说明校验只防目录跳出，不防越权）。
4. Windows 保留设备名（CON/AUX/NUL/PRN）能通过 id 正则，但无法创建用户目录。

运行：python tests/security/poc_multiuser_isolation.py
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from _harness import Dashboard, check, clean_env, finish, request

from qf_wire.config.loader import ConfigError, resolve_paths, resolve_user
from qf_wire.core.models import SourceItem
from qf_wire.core.scheduler import today_beijing
from qf_wire.sources.base import FetchResult
from qf_wire.storage.sqlite import WireStore


def seed_user_dir(base_data: Path, user: str, items: int) -> Path:
    user_dir = base_data / "users" / user
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "data.js").write_text(
        'window.DATA = {"owner": "%s"};' % user, encoding="utf-8"
    )
    now = datetime.now(timezone.utc)
    store = WireStore(user_dir / "wire.db")
    try:
        store.record_run(
            run_id=f"poc-{user}",
            day=today_beijing(),
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
                        title=f"{user} item {index}",
                        url="http://127.0.0.1/1",
                        source_id="feed_a",
                        topic="semi",
                    )
                    for index in range(items)
                ]
            },
            events_by_topic={},
        )
    finally:
        store.close()
    return user_dir


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="qf-poc-multiuser-") as raw_tmp:
        tmp = Path(raw_tmp)
        with clean_env(tmp / ".env.local"), Dashboard(tmp) as dash:
            base_data = tmp / "data"
            seed_user_dir(base_data, "alice", 1)
            seed_user_dir(base_data, "bob", 2)

            os.environ["QF_WIRE_MULTIUSER"] = "true"

            status, _, alice = request(
                dash.base, "/data.js", headers={"X-QF-User": "alice"}
            )
            check(status == 200 and b'"alice"' in alice, "回环客户端无需凭据即可读 alice 的 data.js")

            status, _, bob = request(dash.base, "/data.js", headers={"X-QF-User": "bob"})
            check(status == 200 and b'"bob"' in bob, "同一客户端改一个头即可读 bob 的 data.js")

            day = today_beijing().isoformat()
            status, _, payload = request(
                dash.base, f"/api/history?date={day}", headers={"X-QF-User": "alice"}
            )
            check(status == 200, "可读取 alice 的 wire.db 历史")
            status, _, payload = request(
                dash.base, f"/api/history?date={day}", headers={"X-QF-User": "bob"}
            )
            check(status == 200, "可读取 bob 的 wire.db 历史")

            os.environ["QF_WIRE_API_TOKEN"] = "poc-shared-token-not-a-real-secret"
            os.environ["QF_WIRE_API_REQUIRE_TOKEN"] = "1"
            auth = {"Authorization": "Bearer poc-shared-token-not-a-real-secret"}

            status, _, alice = request(
                dash.base, "/data.js", headers={**auth, "X-QF-User": "alice"}
            )
            check(status == 200 and b'"alice"' in alice, "同一个全局 token 可读 alice")
            status, _, bob = request(
                dash.base, "/data.js", headers={**auth, "X-QF-User": "bob"}
            )
            check(status == 200 and b'"bob"' in bob, "同一个全局 token 也可读 bob（无每用户授权）")

            status, _, payload = request(
                dash.base, "/data.js", headers={**auth, "X-QF-User": "../escape"}
            )
            check(status == 400, "对照：路径穿越 id 被拒绝（400）")

            for bad in ("café", "a" * 65, "..", "a/b"):
                status, _, _ = request(
                    dash.base, "/data.js", headers={**auth, "X-QF-User": bad}
                )
                check(status == 400, f"对照：非法 id {bad!r} 被拒绝")

            for reserved in ("CON", "AUX", "NUL", "PRN"):
                accepted = True
                try:
                    resolve_user(reserved)
                except ConfigError:
                    accepted = False
                check(accepted, f"Windows 保留设备名 {reserved} 通过用户 id 正则校验")

            paths = resolve_paths(
                dash.config.paths.config_dir, dash.config.paths.data_dir, user="CON"
            )
            if os.name == "nt":
                try:
                    paths.ensure()
                except OSError as exc:
                    check(True, f"Windows 上创建 CON 用户目录失败（{type(exc).__name__}）")
                else:
                    check(False, "Windows 上创建 CON 用户目录意外成功")
            else:
                check(
                    True,
                    "非 Windows 平台不受保留设备名影响（该风险仅在 Windows 触发）",
                )

    finish("poc_multiuser_isolation")


if __name__ == "__main__":
    main()
