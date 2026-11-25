"""Локальный корень доверия Pygram.

Отпечаток супер-администратора хранится на конкретном компьютере, а не в SMB.
Общая папка считается недоверенной до ручной сверки отпечатка.
"""

from __future__ import annotations

import re
import json
import os
import tempfile
from pathlib import Path
from typing import Callable

from src.core.crypto import fingerprint
from src.os_integration.win import get_local_dir

TRUST_FILE = "trusted_root.json"


class TrustError(ValueError):
    """Ошибка проверки или настройки локального корня доверия."""


def trust_path() -> Path:
    return get_local_dir() / TRUST_FILE


def admin_signature_payload(entry: dict) -> bytes:
    """Payload v2: подпись включает каждое право администратора."""
    fields = (
        "fp16",
        "added_at",
        "added_by",
        "is_super",
        "can_manage_admins",
        "can_read_all_chats",
        "can_grant_delete_rights",
    )
    payload = {field: entry[field] for field in fields}
    payload["signature_version"] = 2
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _legacy_admin_signature_payload(entry: dict) -> bytes:
    """Payload v1 для проверки уже существующих подписей до обновления."""
    fields = (
        "fp16", "added_at", "added_by", "is_super",
        "can_manage_admins", "can_read_all_chats",
    )
    payload = {field: entry[field] for field in fields}
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")



def _read_pin() -> dict | None:
    path = trust_path()

    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrustError(
            "Локальная запись доверия повреждена. Вход заблокирован."
        ) from exc

    if not isinstance(data, dict):
        raise TrustError("Неверный формат локальной записи доверия.")

    base_fields = {"version", "fp16", "fingerprint"}
    recovery_fields = {"recovery_fingerprint", "recovery_public_key"}
    if set(data) not in (base_fields, base_fields | recovery_fields):
        raise TrustError("Неверный формат локальной записи доверия.")

    if type(data["version"]) is not int or data["version"] not in (1, 2):
        raise TrustError("Неизвестная версия локальной записи доверия.")
    has_recovery = recovery_fields.issubset(data)
    if (data["version"] == 2) != has_recovery:
        raise TrustError("Неверная версия ключа восстановления в записи доверия.")

    fp16 = data["fp16"]
    full_fingerprint = data["fingerprint"]

    if not isinstance(fp16, str) or not re.fullmatch(
        r"[0-9a-fA-F]{16}", fp16
    ):
        raise TrustError("Некорректный короткий fingerprint.")

    if not isinstance(full_fingerprint, str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", full_fingerprint
    ):
        raise TrustError("Некорректный полный fingerprint.")

    if not full_fingerprint.lower().startswith(fp16.lower()):
        raise TrustError("Fingerprint не соответствует fp16.")

    result = {
        "version": data["version"],
        "fp16": fp16.lower(),
        "fingerprint": full_fingerprint.lower(),
    }
    if has_recovery:
        recovery_fp = data["recovery_fingerprint"]
        recovery_pub = data["recovery_public_key"]
        if (
            not isinstance(recovery_fp, str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", recovery_fp)
            or not isinstance(recovery_pub, str)
        ):
            raise TrustError("Некорректный закреплённый ключ восстановления.")
        from src.core.crypto import fingerprint as key_fingerprint
        if key_fingerprint(recovery_pub).lower() != recovery_fp.lower():
            raise TrustError("Fingerprint ключа восстановления не совпадает.")
        result["recovery_fingerprint"] = recovery_fp.lower()
        result["recovery_public_key"] = recovery_pub
    return result


def _write_pin(
    fp16: str,
    full_fingerprint: str,
    recovery_public_key: str | None = None,
) -> None:
    if not isinstance(fp16, str) or not re.fullmatch(
        r"[0-9a-fA-F]{16}", fp16
    ):
        raise TrustError("Некорректный короткий fingerprint.")

    if not isinstance(full_fingerprint, str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", full_fingerprint
    ):
        raise TrustError("Некорректный полный fingerprint.")

    fp16 = fp16.lower()
    full_fingerprint = full_fingerprint.lower()

    if not full_fingerprint.startswith(fp16):
        raise TrustError("Fingerprint не соответствует fp16.")

    path = trust_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "version": 1,
        "fp16": fp16,
        "fingerprint": full_fingerprint,
    }
    if recovery_public_key is not None:
        from src.core.crypto import fingerprint as key_fingerprint
        recovery_fp = key_fingerprint(recovery_public_key).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", recovery_fp):
            raise TrustError("Некорректный ключ восстановления.")
        data.update({
            "version": 2,
            "recovery_fingerprint": recovery_fp,
            "recovery_public_key": recovery_public_key,
        })

    fd, temp_name = tempfile.mkstemp(
        prefix=".trusted_root_",
        dir=path.parent,
    )

    try:
        with os.fdopen(
            fd, "w", encoding="utf-8", newline="\n"
        ) as stream:
            json.dump(data, stream, ensure_ascii=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temp_name, path)

    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise



def get_root_candidate(shared_folder: str | Path) -> dict | None:
    """Находит и криптографически проверяет самоподписанную запись супер-админа."""
    from src.core.admin import admins_path, verify_signature
    from src.storage.shared_store import load_pub_key_by_fp16, read_json

    path = admins_path(shared_folder)
    if not path.is_file():
        return None
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("admins"), list):
        raise TrustError("Список администраторов повреждён. Вход заблокирован.")

    roots = [entry for entry in data["admins"] if isinstance(entry, dict) and entry.get("is_super") is True]
    if not roots:
        if data["admins"]:
            raise TrustError("В списке администраторов нет доверенного супер-администратора.")
        return None
    if len(roots) != 1:
        raise TrustError("В общей папке найдено несколько супер-администраторов. Вход заблокирован.")

    root = roots[0]
    fp16 = root.get("fp16")
    if not isinstance(fp16, str) or len(fp16) != 16 or root.get("added_by") != fp16:
        raise TrustError("Запись первого супер-администратора не является самоподписанной.")

    try:
        pub_pem = load_pub_key_by_fp16(shared_folder, fp16)
        full_fp = fingerprint(pub_pem)
    except Exception as exc:
        raise TrustError("Не удалось проверить публичный ключ супер-администратора.") from exc

    if not full_fp.startswith(fp16.lower()):
        raise TrustError("Отпечаток публичного ключа не соответствует записи администратора.")
    if not verify_signature(root, pub_pem):
        raise TrustError("Подпись первого супер-администратора недействительна.")

    return {"fp16": fp16, "fingerprint": full_fp, "public_key": pub_pem}


def pin_initial_root(
    shared_folder: str | Path,
    fp16: str,
    recovery_public_key: str | None = None,
) -> None:
    """Закрепляет ключ первого супер-администратора и, если задан, recovery key."""
    if _read_pin() is not None:
        raise TrustError("На этом компьютере уже закреплён корень доверия.")
    candidate = get_root_candidate(shared_folder)
    if candidate is None or candidate["fp16"] != fp16:
        raise TrustError("Не удалось подтвердить созданного первого супер-администратора.")
    if recovery_public_key is None:
        # Для старых тестовых/программных bootstrap-вызовов сохраняется v1.
        _write_pin(candidate["fp16"], candidate["fingerprint"])
    else:
        _write_pin(candidate["fp16"], candidate["fingerprint"], recovery_public_key)


def _try_recovery_migration(pin: dict, shared_folder: str | Path, candidate: dict) -> bool:
    """Принимает новый root только по сертификату от локально закреплённого recovery key."""
    if not pin.get("recovery_public_key"):
        return False
    try:
        from src.core.superadmin_recovery import (
            load_recovery_certificate, verify_recovery_certificate,
        )
        certificate = load_recovery_certificate(shared_folder)
        verified = verify_recovery_certificate(
            certificate, pin["recovery_public_key"]
        )
        if (
            verified["old_root_fp16"] != pin["fp16"].lower()
            or verified["old_root_fingerprint"] != pin["fingerprint"].lower()
            or verified["new_root_fp16"] != candidate["fp16"].lower()
            or verified["new_root_fingerprint"] != candidate["fingerprint"].lower()
        ):
            return False
        # После recovery все сохранённые записи администраторов должны быть
        # непосредственно подписаны новым root. Это не даёт принять старый
        # или подменённый список вместе с новым корнем.
        from src.core.admin import admins_path, verify_signature
        from src.storage.shared_store import read_json, load_pub_key_by_fp16
        roster = read_json(admins_path(shared_folder))
        entries = roster.get("admins") if isinstance(roster, dict) else None
        if not isinstance(entries, list) or not entries:
            return False
        roots = [e for e in entries if isinstance(e, dict) and e.get("is_super") is True]
        if len(roots) != 1 or roots[0].get("fp16") != candidate["fp16"]:
            return False
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("added_by") != candidate["fp16"]:
                return False
            if not verify_signature(entry, candidate["public_key"]):
                return False
        _write_pin(
            candidate["fp16"], candidate["fingerprint"],
            pin["recovery_public_key"],
        )
        return True
    except Exception as exc:
        # Ошибка проверки не должна превращаться в автоматическое доверие.
        from loguru import logger
        logger.warning(f"Проверка сертификата восстановления не пройдена: {exc}")
        return False


def _enroll_recovery_key(pin: dict, shared_folder: str | Path, candidate: dict) -> dict:
    """Для старого v1-pin добавляет recovery key только при прежнем доверенном root."""
    if pin.get("recovery_public_key"):
        return pin
    try:
        from src.core.superadmin_recovery import (
            load_recovery_descriptor, verify_recovery_descriptor,
        )
        descriptor = load_recovery_descriptor(shared_folder)
        verified = verify_recovery_descriptor(descriptor, candidate["public_key"])
        _write_pin(candidate["fp16"], candidate["fingerprint"], verified["public_key"])
        return _read_pin() or pin
    except Exception:
        return pin


def pin_recovered_root(
    fp16: str, full_fingerprint: str, recovery_public_key: str
) -> None:
    """Обновляет локальный pin после успешной recovery-процедуры."""
    _write_pin(fp16, full_fingerprint, recovery_public_key)


def ensure_trusted_root(
    shared_folder: str | Path,
    confirm_callback: Callable[[str], bool] | None = None,
) -> dict | None:
    """Проверяет закреплённый ключ или запрашивает ручное подтверждение.

    На первом компьютере до создания первого аккаунта возвращает None.
    На остальных компьютерах confirm_callback получает полный SHA-256 отпечаток.
    """
    pin = _read_pin()
    candidate = get_root_candidate(shared_folder)

    if candidate is None:
        if pin is not None:
            raise TrustError("Закреплённый супер-администратор отсутствует в общей папке. Вход заблокирован.")
        return None

    if pin is not None:
        if (
            pin["fp16"] != candidate["fp16"]
            or pin["fingerprint"].lower() != candidate["fingerprint"].lower()
        ):
            if _try_recovery_migration(pin, shared_folder, candidate):
                return candidate
            raise TrustError(
                "Ключ супер-администратора изменился! Сертификат восстановления "
                "не подтверждён. Вход заблокирован; не удаляйте локальную запись доверия."
            )
        _enroll_recovery_key(pin, shared_folder, candidate)
        return candidate

    if confirm_callback is None or not confirm_callback(candidate["fingerprint"]):
        raise TrustError("Отпечаток супер-администратора не подтверждён. Вход отменён.")

    recovery_key = None
    try:
        from src.core.superadmin_recovery import (
            load_recovery_descriptor, verify_recovery_descriptor,
        )
        descriptor = load_recovery_descriptor(shared_folder)
        recovery_key = verify_recovery_descriptor(
            descriptor, candidate["public_key"]
        )["public_key"]
    except Exception:
        # Root может быть старой версии без recovery. Сам root всё равно
        # закрепляется после ручной сверки полного отпечатка.
        recovery_key = None
    _write_pin(candidate["fp16"], candidate["fingerprint"], recovery_key)
    return candidate


def require_trusted_root(shared_folder: str | Path) -> dict | None:
    """Проверка для внутренних функций авторизации без UI-подтверждения."""
    pin = _read_pin()
    candidate = get_root_candidate(shared_folder)
    if candidate is None:
        if pin is not None:
            raise TrustError("Закреплённый супер-администратор отсутствует в общей папке.")
        return None
    if pin is None:
        raise TrustError("Сначала вручную подтвердите отпечаток супер-администратора в окне входа.")
    if pin["fp16"] != candidate["fp16"] or pin["fingerprint"].lower() != candidate["fingerprint"].lower():
        if _try_recovery_migration(pin, shared_folder, candidate):
            return candidate
        raise TrustError("Ключ супер-администратора изменился. Доступ заблокирован.")
    _enroll_recovery_key(pin, shared_folder, candidate)
    return candidate


def root_account_available(shared_folder: str | Path, candidate: dict | None = None) -> bool:
    """Проверяет наличие маркера логина, auth и identity-файла текущего root."""
    try:
        from src.storage.shared_store import (
            DIR_LOGINS, auth_path, identity_path,
        )
        root = candidate or get_root_candidate(shared_folder)
        if root is None:
            return False
        fp16 = root["fp16"]
        if not auth_path(shared_folder, fp16).is_file():
            return False
        if not identity_path(shared_folder, fp16).is_file():
            return False
        login_dir = Path(shared_folder) / DIR_LOGINS
        if not login_dir.is_dir():
            return False
        for marker_path in login_dir.iterdir():
            if not marker_path.is_file():
                continue
            try:
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            marker_fp = marker.get("fp") if isinstance(marker, dict) else None
            if isinstance(marker_fp, str) and marker_fp.lower() == root["fingerprint"].lower():
                return True
        return False
    except Exception:
        return False
