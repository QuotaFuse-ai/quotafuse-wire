"""qfw token：生成、复用、轮换与非法用户 id。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qf_wire.cli.main import cli
from qf_wire.core.errors import EXIT_OK, EXIT_PARAM

ENV_NAMES = (
    "QF_WIRE_MULTIUSER",
    "QF_WIRE_USER",
    "QF_WIRE_CONFIG_DIR",
    "QF_WIRE_DATA_DIR",
    "QF_WIRE_PROMPTS_DIR",
    "QF_WIRE_ROOT",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, isolated_env) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _run(tmp_path: Path, *args: str) -> int:
    return cli(
        [
            "-o",
            "json",
            "--config-dir",
            str(tmp_path / "config"),
            "--data-dir",
            str(tmp_path / "data"),
            "token",
            *args,
        ]
    )


def _token_file(tmp_path: Path, user: str) -> Path:
    return tmp_path / "data" / "users" / user / "api.token"


def test_creates_token_in_user_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = _run(tmp_path, "--user", "alice")
    out = json.loads(capsys.readouterr().out)

    assert code == EXIT_OK
    assert out["created"] is True
    assert out["user"] == "alice"
    path = Path(out["path"])
    assert path == _token_file(tmp_path, "alice")
    assert path.read_text(encoding="utf-8").strip() == out["token"]


def test_reuses_existing_token(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = _run(tmp_path, "--user", "alice")
    first = json.loads(capsys.readouterr().out)
    code = _run(tmp_path, "--user", "alice")
    second = json.loads(capsys.readouterr().out)

    assert code == EXIT_OK
    assert second["created"] is False
    assert second["token"] == first["token"]


def test_rotate_invalidates_old_token(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _run(tmp_path, "--user", "alice")
    first = json.loads(capsys.readouterr().out)
    code = _run(tmp_path, "--user", "alice", "--rotate")
    rotated = json.loads(capsys.readouterr().out)

    assert code == EXIT_OK
    assert rotated["created"] is True
    assert rotated["token"] != first["token"]
    assert _token_file(tmp_path, "alice").read_text(encoding="utf-8").strip() == rotated["token"]


@pytest.mark.parametrize("user", ["../escape", "a/b", "a b", ""])
def test_rejects_invalid_user(tmp_path: Path, user: str) -> None:
    code = _run(tmp_path, "--user", user)

    assert code == EXIT_PARAM
    assert not (tmp_path / "escape").exists()


def test_requires_user(tmp_path: Path) -> None:
    code = _run(tmp_path)

    assert code == EXIT_PARAM
