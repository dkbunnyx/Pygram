"""Управление статусами Pygram.

Включает:
- Онлайн / печатает / last_seen (с конфиденциальностью)
- Галочки прочтения
- Реакции
- Удалённые сообщения
- Счётчик непрочитанных

Конфиденциальность:
- hide_last_seen=True скрывает last_seen от не-админов.
- Для не-админа last_seen=0 + флаг _hidden → UI покажет "был(а) недавно".
- Админ с can_read_all_chats видит реальное время.
"""

from __future__ import annotations

from pathlib import Path
import json
import re
import time

from loguru import logger

DIR_STATUS = ".status"

# Формат msg_id: <ts>_<sender_fp16>_<uuid>
_MSG_ID_RE = re.compile(r"^\d+_([0-9a-f]{16})_[0-9a-f]+$", re.IGNORECASE)


# ============================================================================
# ПУТИ
# ============================================================================

def _status_file(shared_folder: Path | str, fp16: str) -> Path:
    path = Path(shared_folder) / DIR_STATUS
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{fp16}.json"


def _read_file(shared_folder: Path | str, chat_id: str, fp16: str) -> Path:
    path = Path(shared_folder) / DIR_STATUS / "read"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{chat_id}_{fp16}.json"


def _reactions_file(shared_folder: Path | str, chat_id: str, msg_id: str) -> Path:
    path = Path(shared_folder) / DIR_STATUS / "reactions"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{chat_id}_{msg_id}.json"


def _deleted_file(shared_folder: Path | str, chat_id: str) -> Path:
    path = Path(shared_folder) / DIR_STATUS / "deleted"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{chat_id}.json"


# ============================================================================
# ОНЛАЙН / ПЕЧАТАЕТ / LAST_SEEN
# ============================================================================

def set_online(
    shared_folder: Path | str,
    fp16: str,
    online: bool,
    hide_last_seen: bool = False,
) -> None:
    """Обновляет онлайн-статус.

    hide_last_seen сохраняется в файле; применяется в get_status()
    (не-админы увидят "был(а) недавно" вместо времени).
    """
    try:
        path = _status_file(shared_folder, fp16)
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}

        data["online"] = online
        data["last_seen"] = int(time.time())
        data["typing"] = data.get("typing", False)
        data["typing_chat"] = data.get("typing_chat", "")
        data["hide_last_seen"] = bool(hide_last_seen)

        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        logger.error(f"Ошибка установки статуса: {e}")


def set_typing(shared_folder: Path | str, fp16: str, chat_id: str, typing: bool) -> None:
    try:
        path = _status_file(shared_folder, fp16)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = {"online": True, "last_seen": int(time.time())}

        data["typing"] = typing
        data["typing_chat"] = chat_id
        data["last_seen"] = int(time.time())
        data.setdefault("hide_last_seen", False)

        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        logger.error(f"Ошибка установки 'печатает': {e}")


def get_status(
    shared_folder: Path | str,
    fp16: str,
    viewer_fp16: str | None = None,
    viewer_is_admin: bool = False,
) -> dict:
    """Возвращает статус. Для не-админа last_seen скрывается при hide_last_seen=True.

    Returns:
        dict с ключами: online, last_seen, typing, typing_chat, hide_last_seen, _hidden.
    """
    default = {
        "online": False, "last_seen": 0, "typing": False,
        "typing_chat": "", "hide_last_seen": False, "_hidden": False,
    }
    try:
        path = _status_file(shared_folder, fp16)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("hide_last_seen") and not viewer_is_admin:
                data["last_seen"] = 0
                data["_hidden"] = True
            return data
    except Exception:
        pass
    return default


# ============================================================================
# ГАЛОЧКИ ПРОЧТЕНИЯ
# ============================================================================

def mark_messages_read(
    shared_folder: Path | str,
    chat_id: str,
    fp16: str,
    msg_ids: list[str],
) -> None:
    try:
        path = _read_file(shared_folder, chat_id, fp16)
        existing: list[str] = []
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


# ============================================================================
# РЕАКЦИИ
# ============================================================================

def set_reaction(
    shared_folder: Path | str,
    chat_id: str,
    msg_id: str,
    fp16: str,
    emoji: str | None,
) -> None:
    try:
        path = _reactions_file(shared_folder, chat_id, msg_id)
        data: dict[str, str] = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))

        if emoji:
            data[fp16] = emoji
        else:
            data.pop(fp16, None)

        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        logger.error(f"Ошибка установки реакции: {e}")


def get_reactions(shared_folder: Path | str, chat_id: str, msg_id: str) -> dict[str, str]:
    try:
        path = _reactions_file(shared_folder, chat_id, msg_id)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


# ============================================================================
# УДАЛЁННЫЕ СООБЩЕНИЯ
# ============================================================================

def delete_message(
    shared_folder: Path | str,
    chat_id: str,
    msg_id: str,
    fp16: str,
    for_everyone: bool = False,
) -> None:
    try:
        path = _deleted_file(shared_folder, chat_id)
        data: dict = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))

        if for_everyone:
            data.setdefault("all", [])
            if msg_id not in data["all"]:
                data["all"].append(msg_id)
        else:
            data.setdefault(fp16, [])
            if msg_id not in data[fp16]:
                data[fp16].append(msg_id)

        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения: {e}")


def get_deleted_messages(
    shared_folder: Path | str,
    chat_id: str,
    fp16: str,
) -> list[str]:
    try:
        path = _deleted_file(shared_folder, chat_id)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("all", []) + data.get(fp16, [])
    except Exception:
        pass
    return []


# ============================================================================
# НЕПРОЧИТАННЫЕ
# ============================================================================

def get_unread_count(shared_folder: Path | str, chat_id: str, my_fp16: str) -> int:
    """Количество непрочитанных сообщений (устойчиво к битым msg_id)."""
    from src.storage.shared_store import chat_message_dir

    try:
        read_by_me = set(get_read_messages(shared_folder, chat_id, my_fp16))
        msg_dir = chat_message_dir(shared_folder, chat_id)

        if not msg_dir.is_dir():
            return 0

        count = 0
        for msg_file in msg_dir.glob("*.bin"):
            msg_id = msg_file.stem
            if msg_id in read_by_me:
                continue

            match = _MSG_ID_RE.match(msg_id)
            if not match:
                continue

            sender = match.group(1)
            if sender != my_fp16:
                count += 1
        return count
    except Exception:
        return 0