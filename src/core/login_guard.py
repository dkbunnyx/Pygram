"""Локальное ограничение неудачных попыток входа в Pygram."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import threading
import time
from pathlib import Path

from src.os_integration.win import get_local_dir

_LOCK = threading.Lock()
_VERSION = 1


def _state_path(login: str) -> Path:
    """Возвращает путь к локальному файлу состояния аккаунта."""
    digest = hashlib.sha256(login.encode("utf-8")).hexdigest()
    return get_local_dir() / f".login_guard_{digest}.json"


def _read_state(path: Path) -> dict:
    """Читает состояние. При отсутствии или повреждении файла начинает с нуля."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))

        if (
            not isinstance(data, dict)
            or type(data.get("version")) is not int
            or data["version"] != _VERSION
            or type(data.get("failures")) is not int
            or data["failures"] < 0
            or type(data.get("locked_until")) is not int
            or data["locked_until"] < 0
        ):
            return {"version": _VERSION, "failures": 0, "locked_until": 0}

        return data

    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {"version": _VERSION, "failures": 0, "locked_until": 0}


def _write_state(path: Path, state: dict) -> None:
    """Атомарно сохраняет состояние в локальный файл."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False).encode("utf-8")

    fd, temp_name = tempfile.mkstemp(
        prefix=".login_guard_",
        suffix=".tmp",
        dir=path.parent,
    )
    temp_path = Path(temp_name)

    try:
        with os.fdopen(fd, "wb") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())

        os.replace(temp_path, path)

    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _lock_duration(failures: int) -> int:
    """Возвращает длительность блокировки по числу ошибок."""
    if failures >= 10:
        return 180
    if failures >= 5:
        return 60
    if failures >= 3:
        return 30
    return 0


def get_lock_remaining(login: str) -> int:
    """Возвращает оставшееся время блокировки в секундах."""
    path = _state_path(login)

    with _LOCK:
        state = _read_state(path)
        remaining = state["locked_until"] - int(time.time())
        return max(0, math.ceil(remaining))


def record_failure(login: str) -> int:
    """Учитывает неверный пароль и возвращает оставшееся время блокировки."""
    path = _state_path(login)

    with _LOCK:
        state = _read_state(path)
        now = int(time.time())

        if state["locked_until"] > now:
            return state["locked_until"] - now

        failures = state["failures"] + 1
        duration = _lock_duration(failures)

        state = {
            "version": _VERSION,
            "failures": failures,
            "locked_until": now + duration if duration else 0,
        }

        _write_state(path, state)
        return duration


def reset_attempts(login: str) -> None:
    """Сбрасывает счётчик после успешного входа."""
    path = _state_path(login)

    with _LOCK:
        path.unlink(missing_ok=True)
