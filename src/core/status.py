"""Управление статусами пользователей (в сети, печатает, прочитано, реакции, удаленные)."""

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

# --- ГАЛОЧКИ ПРОЧТЕНИЯ ---

def _read_file(shared_folder: Path | str, chat_id: str, fp16: str) -> Path:
    path = Path(shared_folder) / DIR_STATUS / "read"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{chat_id}_{fp16}.json"

def mark_messages_read(shared_folder: Path | str, chat_id: str, fp16: str, msg_ids: list[str]):
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
    try:
        path = _read_file(shared_folder, chat_id, fp16)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

# --- РЕАКЦИИ ---

def _reactions_file(shared_folder: Path | str, chat_id: str, msg_id: str) -> Path:
    path = Path(shared_folder) / DIR_STATUS / "reactions"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{chat_id}_{msg_id}.json"

def set_reaction(shared_folder: Path | str, chat_id: str, msg_id: str, fp16: str, emoji: str | None):
    try:
        path = _reactions_file(shared_folder, chat_id, msg_id)
        data = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))

        if emoji:
            data[fp16] = emoji
        else:
            data.pop(fp16, None)

        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        logger.error(f"Ошибка установки реакции: {e}")

def get_reactions(shared_folder: Path | str, chat_id: str, msg_id: str) -> dict:
    try:
        path = _reactions_file(shared_folder, chat_id, msg_id)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

# --- УДАЛЕННЫЕ СООБЩЕНИЯ ---

def _deleted_file(shared_folder: Path | str, chat_id: str) -> Path:
    path = Path(shared_folder) / DIR_STATUS / "deleted"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{chat_id}.json"

def delete_message(shared_folder: Path | str, chat_id: str, msg_id: str, fp16: str, for_everyone: bool = False):
    try:
        path = _deleted_file(shared_folder, chat_id)
        data = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))

        if for_everyone:
            if "all" not in data:
                data["all"] = []
            if msg_id not in data["all"]:
                data["all"].append(msg_id)
        else:
            if fp16 not in data:
                data[fp16] = []
            if msg_id not in data[fp16]:
                data[fp16].append(msg_id)

        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения: {e}")

def get_deleted_messages(shared_folder: Path | str, chat_id: str, fp16: str) -> list[str]:
    try:
        path = _deleted_file(shared_folder, chat_id)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            result = data.get("all", []) + data.get(fp16, [])
            return result
    except Exception:
        pass
    return []

# --- НЕПРОЧИТАННЫЕ ---

def get_unread_count(shared_folder: Path | str, chat_id: str, my_fp16: str) -> int:
    """Возвращает количество непрочитанных сообщений в чате (для любого типа)."""
    from src.storage.shared_store import chat_message_dir

    try:
        read_by_me = get_read_messages(shared_folder, chat_id, my_fp16)
        msg_dir = chat_message_dir(shared_folder, chat_id)

        if not msg_dir.is_dir():
            return 0

        count = 0
        for msg_file in msg_dir.glob("*.bin"):
            msg_id = msg_file.stem
            if msg_id in read_by_me:
                continue
            parts = msg_id.split("_")
            if len(parts) >= 2:
                sender = parts[1]
                if sender != my_fp16:
                    count += 1
        return count
    except Exception:
        return 0