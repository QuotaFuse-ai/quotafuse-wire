"""Docker 部署文件静态校验；不依赖 Docker 守护进程。"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _service() -> dict:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    return compose["services"]["wire"]


def test_compose_publishes_dashboard_on_loopback_only() -> None:
    ports = _service()["ports"]

    assert ports == ["127.0.0.1:8790:8790"]


def test_compose_runs_scheduler_and_sets_container_config() -> None:
    service = _service()

    assert "--with-scheduler" in service["command"]
    assert service["environment"]["QF_WIRE_DATA_DIR"] == "/data"
    assert service["environment"]["QF_WIRE_CONFIG_DIR"] == "/app/config"


def test_compose_healthcheck_hits_health_endpoint() -> None:
    health = _service()["healthcheck"]

    assert health["test"][0] == "CMD"
    assert "/api/health" in " ".join(health["test"])
    assert "QF_WIRE_API_TOKEN" in " ".join(health["test"])


def test_compose_mounts_user_data_and_config() -> None:
    volumes = _service()["volumes"]

    assert "./data:/data" in volumes
    assert "./config:/app/config" in volumes


def test_dockerfile_does_not_copy_user_data_or_old_mcp_port() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    copy_lines = [
        line for line in dockerfile.splitlines() if line.strip().upper().startswith("COPY")
    ]

    assert copy_lines
    assert not any(re.search(r"(^|\s)data(\s|$)", line) for line in copy_lines)
    assert "EXPOSE 8790" in dockerfile
    assert "8791" not in dockerfile


def test_dockerignore_excludes_secrets_and_data() -> None:
    patterns = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    assert "data/" in patterns
    assert ".env*" in patterns
    assert "!.env.example" in patterns
