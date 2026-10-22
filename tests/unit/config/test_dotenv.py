"""`.env` 解析与优先级：真实环境变量 > .env.local > .env。"""
from __future__ import annotations

import pytest

from qf_wire.config.dotenv import first_env, load_dotenv, parse_dotenv, write_env_file

KEYS = ("DOTENV_MODEL", "DOTENV_BASE", "DOTENV_KEY")


def test_parse_dotenv_handles_quotes_comments_and_empty_values() -> None:
    text = """
    # comment
    export DOTENV_MODEL="quoted model"
    DOTENV_BASE=https://example.invalid/v1  # inline comment
    DOTENV_KEY=
    NOT_A_PAIR
    """
    values = parse_dotenv(text)

    assert values == {
        "DOTENV_MODEL": "quoted model",
        "DOTENV_BASE": "https://example.invalid/v1",
    }


def test_load_dotenv_prefers_local_and_real_env(tmp_path, monkeypatch) -> None:
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(
        "DOTENV_MODEL=from-env\nDOTENV_BASE=from-env\nDOTENV_KEY=from-env\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.local").write_text("DOTENV_MODEL=from-local\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DOTENV_KEY", "from-real-env")

    path = load_dotenv()

    assert path == tmp_path / ".env.local"
    import os

    assert os.environ["DOTENV_MODEL"] == "from-local"
    assert os.environ["DOTENV_BASE"] == "from-env"
    assert os.environ["DOTENV_KEY"] == "from-real-env"


def test_first_env_skips_blank_values(monkeypatch) -> None:
    monkeypatch.setenv("DOTENV_MODEL", "   ")
    monkeypatch.setenv("DOTENV_BASE", "https://example.invalid/v1")

    assert first_env("DOTENV_MODEL", "DOTENV_BASE") == "https://example.invalid/v1"
    assert first_env("DOTENV_MODEL") is None


def test_missing_env_file_returns_none(tmp_path) -> None:
    assert load_dotenv(tmp_path / "missing.env") is None


def test_write_env_file_merges_and_removes(tmp_path) -> None:
    target = tmp_path / ".env.local"
    target.write_text("# 注释保留\nOTHER=keep-me\nDOTENV_MODEL=old\n", encoding="utf-8")

    write_env_file(target, {"DOTENV_MODEL": "new", "DOTENV_KEY": "sk-test", "OTHER": ""})

    text = target.read_text(encoding="utf-8")
    assert "# 注释保留" in text
    assert "OTHER=" not in text
    assert "DOTENV_MODEL=new" in text
    assert "DOTENV_KEY=sk-test" in text
    assert text.count("DOTENV_MODEL") == 1


def test_write_env_file_round_trips_quoted_values(tmp_path) -> None:
    target = tmp_path / ".env.local"

    write_env_file(target, {"DOTENV_MODEL": "my model #1"})

    assert parse_dotenv(target.read_text(encoding="utf-8"))["DOTENV_MODEL"] == "my model #1"


def test_write_env_file_rejects_header_injection(tmp_path) -> None:
    target = tmp_path / ".env.local"

    with pytest.raises(ValueError):
        write_env_file(target, {"DOTENV_KEY": "sk-x\nDOTENV_MODEL=evil"})
    assert not target.exists()
