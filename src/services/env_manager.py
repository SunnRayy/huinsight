"""Env manager — API-key status and local key writes.

Where keys come from:
- Local: the project `.env`, loaded into os.environ at startup.
- Cloud Run (UIS_GCS_BUCKET set): Secret Manager env vars. A `.env` written
  inside the container never reaches the running process and is lost on
  restart, so keys cannot be saved from the app there.

Status reports os.environ, i.e. the key the running server actually uses.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_PATH = Path(__file__).parents[2] / ".env"

KEY_SOURCE_ENV_FILE = "env_file"
KEY_SOURCE_SECRET_MANAGER = "secret_manager"


class KeysNotEditableError(RuntimeError):
    """Raised when a key write is attempted where keys are managed outside the app."""


def key_source() -> str:
    """Return where API keys are managed: 'secret_manager' on cloud, else 'env_file'."""
    return KEY_SOURCE_SECRET_MANAGER if os.environ.get("UIS_GCS_BUCKET") else KEY_SOURCE_ENV_FILE


def keys_editable() -> bool:
    """True when the app can save API keys itself (local `.env`)."""
    return key_source() == KEY_SOURCE_ENV_FILE


def get_key_status(env_var: str) -> str:
    """Return 'configured' if the running server has a non-empty value for env_var."""
    return "configured" if os.environ.get(env_var) else "missing"


def update_key(env_var: str, value: str) -> None:
    """Write a key to `.env` and apply it to the running process.

    Preserves all other `.env` lines and comments. Raises KeysNotEditableError
    on cloud, where keys live in Secret Manager.
    """
    if not keys_editable():
        raise KeysNotEditableError(
            f"{env_var} is managed in Secret Manager on this deployment"
        )
    from dotenv import set_key  # noqa: PLC0415
    set_key(str(ENV_PATH), env_var, value)
    # load_dotenv() never overrides an existing env var, so without this the
    # server would keep using the old key until restart.
    os.environ[env_var] = value
