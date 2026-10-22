"""兼容性测试：旧入口 fetch.py / digest.py / server.py 委托给 qfw。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPAT_DIR = REPO_ROOT / "compatibility"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"compat_{name}", COMPAT_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    import qf_wire.cli.main as cli_main

    recorded: list[list[str]] = []

    def fake_cli(argv: list[str]) -> int:
        recorded.append(list(argv))
        return 8

    monkeypatch.setattr(cli_main, "cli", fake_cli)
    return recorded


def test_fetch_delegates_to_run_sources_only(calls: list[list[str]], capsys: pytest.CaptureFixture[str]) -> None:
    module = _load("fetch")
    code = module.main(["--topic", "semiconductor"])
    assert code == 8
    assert calls == [["run", "--sources-only", "--topic", "semiconductor"]]
    assert "qfw run --sources-only" in capsys.readouterr().err


def test_digest_delegates_to_digest(calls: list[list[str]]) -> None:
    module = _load("digest")
    assert module.main(["--date", "2026-10-22"]) == 8
    assert calls == [["digest", "--date", "2026-10-22"]]


def test_server_defaults_to_legacy_port(calls: list[list[str]]) -> None:
    module = _load("server")
    assert module.main([]) == 8
    assert calls == [["serve", "--port", "8793"]]


def test_server_keeps_explicit_port(calls: list[list[str]]) -> None:
    module = _load("server")
    assert module.main(["--port", "9000"]) == 8
    assert calls == [["serve", "--port", "9000"]]

    assert module.main(["--port=9100"]) == 8
    assert calls[-1] == ["serve", "--port=9100"]


@pytest.mark.parametrize("name", ["fetch", "digest", "server"])
def test_missing_package_hint(
    name: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load(name)
    monkeypatch.setitem(sys.modules, "qf_wire.cli.main", None)
    assert module.main([]) == 3
    assert "pip install -e ." in capsys.readouterr().err


def _load_root(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"root_{name}", REPO_ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["fetch", "digest", "server"])
def test_root_shims_delegate_to_compatibility(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    target = importlib.import_module(f"compatibility.{name}")
    calls: list[list[str] | None] = []

    def fake_main(argv: list[str] | None = None) -> int:
        calls.append(argv)
        return 42

    monkeypatch.setattr(target, "main", fake_main)
    shim = _load_root(name)
    assert shim.main(["--topic", "semi"]) == 42
    assert calls == [["--topic", "semi"]]

