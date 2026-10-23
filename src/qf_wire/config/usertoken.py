"""多用户 API 凭据：每个用户一份随机 token，存放在其数据目录下。

`X-QF-User` 只负责选择用户，不能单独作为身份；多用户共享实例上切换用户
必须同时出示目标用户的 token（见 docs/decisions/0006）。
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

TOKEN_FILENAME = "api.token"
TOKEN_BYTES = 32


def user_token_path(base_data_dir: Path, user: str) -> Path:
    return base_data_dir / "users" / user / TOKEN_FILENAME


def read_user_token(base_data_dir: Path, user: str) -> str:
    """读取用户 token；不存在或不可读时返回空串（调用方按未授权处理）。"""
    try:
        return user_token_path(base_data_dir, user).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def ensure_user_token(base_data_dir: Path, user: str, rotate: bool = False) -> tuple[str, Path, bool]:
    """返回 (token, 路径, 是否新生成)；默认复用已有凭据。"""
    path = user_token_path(base_data_dir, user)
    if not rotate:
        existing = read_user_token(base_data_dir, user)
        if existing:
            return existing, path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(TOKEN_BYTES)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return token, path, True
