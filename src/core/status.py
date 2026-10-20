"""Управление статусами пользователей (в сети, печатает, прочитано)."""

from pathlib import Path
import json
import time
from loguru import logger

DIR_STATUS = ".status"

def _status_file(shared_folder: Path | str, fp16: str) -> Path:
    path = Path(shared_folder) / DIR_STATUS
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{fp16}.json"

def set_online(shared_folder: Path | str, fp16: str, online: bool):
    try:
        data = {"online": online, "last_seen": int(time.time()), "typing": False, "typing_chat": ""}
        _status_file(shared_folder, fp16).write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        logger.error(f"Ошибка установки статуса: {e}")

def set_typing(shared_folder: Path | str, fp16: str, chat_id: str, typing: bool):
    try:
        path = _status_file(shared_folder, fp16)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = {"online": True, "last_seen": int(time.time())}

        data["typing"] = typing
        data["typing_chat"] = chat_id
        data["last_seen"] = int(time.time())

        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        logger.error(f"Ошибка установки 'печатает': {e}")

def get_status(shared_folder: Path | str, fp16: str) -> dict:
    try:
        path = _status_file(shared_folder, fp16)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"online": False, "last_seen": 0, "typing": False, "typing_chat": ""}

# --- ФУНКЦИИ ДЛЯ ГАЛОЧЕК ПРОЧТЕНИЯ ---

def _read_file(shared_folder: Path | str, chat_id: str, fp16: str) -> Path:
    path = Path(shared_folder) / DIR_STATUS / "read"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{chat_id}_{fp16}.json"

def mark_messages_read(shared_folder: Path | str, chat_id: str, fp16: str, msg_ids: list[str]):
    """Отмечает сообщения как прочитанные для пользователя."""
    try:
        path = _read_file(shared_folder, chat_id, fp16)
        existing = []
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))

        new_list = list(set(existing + msg_ids))
        path.write_text(json.dumps(new_list), encoding="utf-8")
    except Exception as e:
        logger.error(f"Ошибка отметки прочтения: {e}")

def get_read_messages(shared_folder: Path | str, chat_id: str, fp16: str) -> list[str]:
    """Возвращает список прочитанных msg_id для пользователя."""
    try:
        path = _read_file(shared_folder, chat_id, fp16)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []