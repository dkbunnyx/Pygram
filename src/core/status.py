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

Конкурентность и SMB:
- Все записи — через write_json_atomic (с retry и fallback).
- Read-modify-write защищён _locked_update() — best-effort lock
  через .lock-файл с O_CREAT|O_EXCL и таймаутом.
- .lock старше _LOCK_STALE_AGE считается залипшим (процесс упал)
  и удаляется.
- На уровне публичных set_* функций — retry на транзиентные
  ошибки SMB (WinError 5).
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from loguru import logger

from src.storage.shared_store import write_json_atomic

DIR_STATUS = ".status"

# Формат msg_id: <ts>_<sender_fp16>_<uuid>
_MSG_ID_RE = re.compile(r"^\d+_([0-9a-f]{16})_[0-9a-f]+$", re.IGNORECASE)

# Таймаут захвата lock-файла (сек) и пауза между попытками
_LOCK_TIMEOUT = 2.0
_LOCK_RETRY_DELAY = 0.05
_LOCK_STALE_AGE = 30.0  # lock старше 30 сек считаем залипшим

# Сколько раз повторять публичную запись при транзиентных SMB-ошибках
_WRITE_RETRIES = 3


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
# БЕЗОПАСНОЕ ЧТЕНИЕ / ЗАПИСЬ
# ============================================================================

def _safe_read_json(path: Path, default):
    """Читает JSON. Битый/отсутствующий файл → default (не падаем)."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Битый JSON {path}: {e}. Использую default.")
        return default


def _locked_update(path: Path, default, mutator):
    """Read-modify-write под best-effort lock.

    На SMB:
      - .lock может залипнуть (процесс упал) → удаляем по возрасту;
      - os.open может упасть с WinError 5 → пробуем ещё раз.

    Args:
        path: JSON-файл.
        default: Значение, если файла нет.
        mutator: Функция(data) -> None. Модифицирует data in-place.

    Возвращает то, что вернул mutator (для удобства).
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_fd = None
    deadline = time.monotonic() + _LOCK_TIMEOUT

    while True:
        try:
            lock_fd = os.open(
                str(lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
            break
        except FileExistsError:
            # Залипший lock? (процесс упал, не удалил)
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > _LOCK_STALE_AGE:
                    logger.warning(
                        f"Stale lock (age {age:.0f}s), removing: {lock_path}"
                    )
                    lock_path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass

            if time.monotonic() >= deadline:
                logger.warning(
                    f"Lock timeout на {lock_path}, пишу без блокировки"
                )
                break
            time.sleep(_LOCK_RETRY_DELAY)
        except OSError as e:
            logger.error(f"Ошибка lock-файла {lock_path}: {e}")
            break

    try:
        data = _safe_read_json(path, default)
        result = mutator(data)
        write_json_atomic(path, data)  # внутри retry + fallback
        return result
    finally:
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except OSError:
                pass
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass


def _retry_write(fn, *args, **kwargs):
    """Повторяет запись при транзиентных ошибках SMB (WinError 5).

    Args:
        fn: Что вызывать (например, лямбду с _locked_update).
        *args, **kwargs: Аргументы fn.

    Returns:
        Результат fn при успехе, иначе None (после последней неудачи).
    """
    last_err = None
    for attempt in range(_WRITE_RETRIES):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt < _WRITE_RETRIES - 1:
                time.sleep(0.1 * (attempt + 1))  # 100, 200 мс
    logger.warning(f"write failed after {_WRITE_RETRIES} attempts: {last_err}")
    return None


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

        def mutate(data: dict) -> None:
            data["online"] = online
            data["last_seen"] = int(time.time())
            data["typing"] = data.get("typing", False)
            data["typing_chat"] = data.get("typing_chat", "")
            data["hide_last_seen"] = bool(hide_last_seen)

        _retry_write(_locked_update, path, {}, mutate)
    except Exception as e:
        logger.error(f"Ошибка установки статуса: {e}")


def set_typing(shared_folder: Path | str, fp16: str, chat_id: str, typing: bool) -> None:
    try:
        path = _status_file(shared_folder, fp16)

        def mutate(data: dict) -> None:
            data.setdefault("online", True)
            data["typing"] = typing
            data["typing_chat"] = chat_id
            data["last_seen"] = int(time.time())
            data.setdefault("hide_last_seen", False)

        _retry_write(
            _locked_update,
            path,
            {"online": True, "last_seen": int(time.time())},
            mutate,
        )
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
        data = _safe_read_json(path, None)
        if data is None:
            return default
        if data.get("hide_last_seen") and not viewer_is_admin:
            data["last_seen"] = 0
            data["_hidden"] = True
        return data
    except Exception:
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
    if not msg_ids:
        return
    try:
        path = _read_file(shared_folder, chat_id, fp16)

        def mutate(data: list) -> None:
            existing = set(data) if isinstance(data, list) else set()
            existing.update(msg_ids)
            data.clear()
            data.extend(sorted(existing))

        _retry_write(_locked_update, path, [], mutate)
    except Exception as e:
        logger.error(f"Ошибка отметки прочтения: {e}")


def get_read_messages(shared_folder: Path | str, chat_id: str, fp16: str) -> list[str]:
    try:
        path = _read_file(shared_folder, chat_id, fp16)
        data = _safe_read_json(path, [])
        return data if isinstance(data, list) else []
    except Exception:
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

        def mutate(data: dict) -> None:
            if emoji:
                data[fp16] = emoji
            else:
                data.pop(fp16, None)

        _retry_write(_locked_update, path, {}, mutate)
    except Exception as e:
        logger.error(f"Ошибка установки реакции: {e}")


def get_reactions(shared_folder: Path | str, chat_id: str, msg_id: str) -> dict[str, str]:
    try:
        path = _reactions_file(shared_folder, chat_id, msg_id)
        data = _safe_read_json(path, {})
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_reaction_users(
    shared_folder: Path | str, chat_id: str, msg_id: str
) -> dict[str, str]:
    """Возвращает словарь {fp16: emoji} для указанного сообщения."""
    return get_reactions(shared_folder, chat_id, msg_id)


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

        def mutate(data: dict) -> None:
            if for_everyone:
                lst = data.setdefault("all", [])
                if msg_id not in lst:
                    lst.append(msg_id)
            else:
                lst = data.setdefault(fp16, [])
                if msg_id not in lst:
                    lst.append(msg_id)

        _retry_write(_locked_update, path, {}, mutate)
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения: {e}")


def get_deleted_messages(
    shared_folder: Path | str,
    chat_id: str,
    fp16: str,
) -> list[str]:
    try:
        path = _deleted_file(shared_folder, chat_id)
        data = _safe_read_json(path, {})
        if not isinstance(data, dict):
            return []
        return list(data.get("all", [])) + list(data.get(fp16, []))
    except Exception:
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
