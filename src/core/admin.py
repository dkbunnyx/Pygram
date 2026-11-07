"""Управление администраторами Pygram.

Каждая запись подписывается назначившим администратором. Первая запись
самоподписывается ключом первого супер-администратора, отпечаток которого
закрепляется локально на каждом компьютере.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from loguru import logger

from src.core.crypto import (fingerprint, from_base64, rsa_sign, rsa_verify,
                             to_base64)
from src.core.trust import (TrustError, admin_signature_payload,
                            require_trusted_root)
from src.storage.shared_store import (DIR_ADMINS, ensure_shared_structure,
                                      load_pub_key_by_fp16, read_json,
                                      safe_join, write_json_atomic)

ADMINS_FILE = "list.json"
MAX_ADMINS_FILE_SIZE = 1024 * 1024  # 1 МиБ
MAX_ADMINS_COUNT = 100

DELETE_RIGHTS_FILE = "delete_rights.json"
MAX_DELETE_RIGHTS_FILE_SIZE = 1024 * 1024
MAX_DELETE_RIGHTS_COUNT = 10000


def admins_path(shared_folder: Path | str) -> Path:
    return safe_join(shared_folder, DIR_ADMINS, ADMINS_FILE)


def delete_rights_path(shared_folder: Path | str) -> Path:
    return safe_join(shared_folder, DIR_ADMINS, DELETE_RIGHTS_FILE)


def _load_list(shared_folder: Path | str) -> dict:
    path = admins_path(shared_folder)

    if not path.is_file():
        return {"admins": []}

    try:
        with path.open("rb") as file:
            raw_data = file.read(MAX_ADMINS_FILE_SIZE + 1)
    except OSError:
        raise

    if len(raw_data) > MAX_ADMINS_FILE_SIZE:
        raise ValueError(
            "Файл списка администраторов превышает допустимый размер (1 МиБ)"
        )

    try:
        data = json.loads(raw_data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(
            f"Некорректный JSON в файле списка администраторов: {e}"
        ) from e

    if not isinstance(data, dict) or not isinstance(data.get("admins"), list):
        raise ValueError("Некорректный список администраторов")

    if len(data["admins"]) > MAX_ADMINS_COUNT:
        raise ValueError(
            f"В списке администраторов превышен лимит ({MAX_ADMINS_COUNT})"
        )

    if not all(isinstance(entry, dict) for entry in data["admins"]):
        raise ValueError("Некорректная запись администратора")

    return data


def _save_list(shared_folder: Path | str, data: dict) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("admins"), list):
        raise ValueError("Некорректный список администраторов")

    admins = data["admins"]

    if len(admins) > MAX_ADMINS_COUNT:
        raise ValueError(f"Нельзя сохранить больше {MAX_ADMINS_COUNT} администраторов")

    if not all(isinstance(entry, dict) for entry in admins):
        raise ValueError("Некорректная запись администратора")

    serialized = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")

    if len(serialized) > MAX_ADMINS_FILE_SIZE:
        raise ValueError(
            "Файл списка администраторов превышает допустимый размер (1 МиБ)"
        )

    write_json_atomic(admins_path(shared_folder), data)


def _load_delete_rights(shared_folder: Path | str) -> dict:
    path = delete_rights_path(shared_folder)

    if not path.is_file():
        return {"rights": []}

    try:
        with path.open("rb") as file:
            raw_data = file.read(MAX_DELETE_RIGHTS_FILE_SIZE + 1)
    except OSError:
        raise

    if len(raw_data) > MAX_DELETE_RIGHTS_FILE_SIZE:
        raise ValueError("Файл пользовательских разрешений превышает 1 МиБ")

    try:
        data = json.loads(raw_data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(
            f"Некорректный JSON в файле пользовательских разрешений: {e}"
        ) from e

    if not isinstance(data, dict) or not isinstance(data.get("rights"), list):
        raise ValueError("Некорректный список пользовательских разрешений")

    if len(data["rights"]) > MAX_DELETE_RIGHTS_COUNT:
        raise ValueError(
            f"В списке разрешений превышен лимит ({MAX_DELETE_RIGHTS_COUNT})"
        )

    if not all(isinstance(entry, dict) for entry in data["rights"]):
        raise ValueError("Некорректная запись пользовательского разрешения")

    return data


def _save_delete_rights(shared_folder: Path | str, data: dict) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("rights"), list):
        raise ValueError("Некорректный список пользовательских разрешений")

    rights = data["rights"]

    if len(rights) > MAX_DELETE_RIGHTS_COUNT:
        raise ValueError(
            f"Нельзя сохранить больше {MAX_DELETE_RIGHTS_COUNT} разрешений"
        )

    if not all(isinstance(entry, dict) for entry in rights):
        raise ValueError("Некорректная запись пользовательского разрешения")

    serialized = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")

    if len(serialized) > MAX_DELETE_RIGHTS_FILE_SIZE:
        raise ValueError("Файл пользовательских разрешений превышает 1 МиБ")

    path = delete_rights_path(shared_folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, data)


def delete_right_signature_payload(entry: dict) -> bytes:
    fields = (
        "fp16",
        "granted",
        "added_at",
        "added_by",
    )

    payload = {field: entry[field] for field in fields}

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _validate_delete_right_entry(entry: dict) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("fp16"), str)
        and re.fullmatch(r"[0-9a-fA-F]{16}", entry["fp16"]) is not None
        and type(entry.get("granted")) is bool
        and type(entry.get("added_at")) is int
        and entry["added_at"] > 0
        and isinstance(entry.get("added_by"), str)
        and re.fullmatch(r"[0-9a-fA-F]{16}", entry["added_by"]) is not None
        and isinstance(entry.get("signature"), str)
        and bool(entry["signature"])
    )


def _load_delete_rights_verified(shared_folder: Path | str) -> dict[str, dict]:
    data = _load_delete_rights(shared_folder)
    admins = load_admins_verified(shared_folder)

    verified_admins = {entry["fp16"]: entry for entry in admins}
    verified_rights = {}

    for entry in data["rights"]:
        if not _validate_delete_right_entry(entry):
            raise ValueError("Некорректная запись пользовательского разрешения")

        target_fp = entry["fp16"]
        signer_fp = entry["added_by"]

        if target_fp in verified_rights:
            raise ValueError("Обнаружены повторяющиеся записи разрешений")

        signer = verified_admins.get(signer_fp)

        if signer is None:
            raise ValueError("Разрешение подписано неизвестным администратором")

        if not (
            signer.get("is_super", False)
            or signer.get("can_grant_delete_rights", False)
        ):
            raise ValueError("У администратора нет права выдавать разрешения")

        if target_fp in verified_admins:
            raise ValueError("Пользовательское разрешение назначено администратору")

        try:
            signer_pub = load_pub_key_by_fp16(shared_folder, signer_fp)
            signature = from_base64(entry["signature"])

            if not rsa_verify(
                signer_pub,
                delete_right_signature_payload(entry),
                signature,
            ):
                raise ValueError(
                    "Недействительная подпись пользовательского разрешения"
                )

        except (ValueError, TypeError, KeyError) as e:
            raise ValueError(
                f"Не удалось проверить разрешение пользователя {target_fp}"
            ) from e

        verified_rights[target_fp] = entry

    return verified_rights


def can_grant_delete_rights(shared_folder: Path | str, fp16: str) -> bool:
    """Проверяет, может ли пользователь выдавать право удаления чужих сообщений."""
    entry = next(
        (a for a in load_admins_verified(shared_folder) if a["fp16"] == fp16),
        None,
    )

    return bool(
        entry
        and (
            entry.get("is_super", False) or entry.get("can_grant_delete_rights", False)
        )
    )


def can_delete_others_messages(shared_folder: Path | str, fp16: str) -> bool:
    """Проверяет право пользователя удалять чужие сообщения у всех."""
    admins = load_admins_verified(shared_folder)

    if any(a["fp16"] == fp16 for a in admins):
        return True

    rights = _load_delete_rights_verified(shared_folder)
    entry = rights.get(fp16)

    return bool(entry and entry["granted"])


def toggle_delete_others_rights(
    shared_folder: Path | str,
    target_fp16: str,
    by: str,
    by_priv: str,
) -> bool:
    """Выдаёт или отзывает право обычному пользователю удалять чужие сообщения."""
    if not isinstance(target_fp16, str) or not re.fullmatch(
        r"[0-9a-fA-F]{16}", target_fp16
    ):
        raise ValueError("Некорректный fp16 пользователя")

    admins = load_admins_verified(shared_folder)
    by_entry = next((a for a in admins if a["fp16"] == by), None)

    if not by_entry or not (
        by_entry.get("is_super", False)
        or by_entry.get("can_grant_delete_rights", False)
    ):
        raise ValueError("Недостаточно прав для изменения разрешения")

    if any(a["fp16"] == target_fp16 for a in admins):
        raise ValueError("Нельзя назначить пользовательское разрешение администратору")

    by_pub = load_pub_key_by_fp16(shared_folder, by)
    probe = rsa_sign(by_priv, b"pygram-delete-right-action-check")

    if not rsa_verify(by_pub, b"pygram-delete-right-action-check", probe):
        raise ValueError("Приватный ключ не соответствует администратору")

    verified_rights = _load_delete_rights_verified(shared_folder)
    current = verified_rights.get(target_fp16)
    new_granted = not bool(current and current["granted"])

    entry = {
        "fp16": target_fp16,
        "granted": new_granted,
        "added_at": int(time.time() * 1000),
        "added_by": by,
    }

    entry["signature"] = to_base64(
        rsa_sign(by_priv, delete_right_signature_payload(entry))
    )

    data = _load_delete_rights(shared_folder)
    data["rights"] = [
        item for item in data["rights"] if item.get("fp16") != target_fp16
    ]
    data["rights"].append(entry)

    _save_delete_rights(shared_folder, data)

    logger.info(
        f"Право удаления чужих сообщений "
        f"{'выдано' if new_granted else 'отозвано'}: "
        f"{target_fp16} (by={by})"
    )

    return new_granted


def load_admins(shared_folder: Path | str) -> list[dict]:
    """Возвращает сырые записи. Не использовать для проверки прав."""
    return _load_list(shared_folder)["admins"]


def load_admins_verified(shared_folder: Path | str) -> list[dict]:
    """Проверяет локально закреплённый root и цепочку подписей администраторов."""
    raw = _load_list(shared_folder)["admins"]
    if not raw:
        require_trusted_root(shared_folder)
        return []

    root = require_trusted_root(shared_folder)
    if root is None:
        raise TrustError(
            "Список администраторов существует, но корень доверия не настроен."
        )

    # Не допускаем неоднозначность: один fp16 должен иметь ровно одну запись.
    fp16_values = [entry.get("fp16") for entry in raw]
    if any(not isinstance(value, str) for value in fp16_values):
        raise TrustError("В списке администраторов есть запись без fingerprint.")
    if len(fp16_values) != len(set(fp16_values)):
        raise TrustError(
            "В списке администраторов обнаружены повторяющиеся fingerprint."
        )

    root_entry = next(
        (
            entry
            for entry in raw
            if entry.get("fp16") == root["fp16"]
            and entry.get("is_super") is True
            and entry.get("added_by") == root["fp16"]
        ),
        None,
    )
    if root_entry is None:
        raise TrustError("Запись закреплённого супер-администратора отсутствует.")

    verified: list[dict] = [root_entry]
    verified_fps = {root["fp16"]}
    pending = [entry for entry in raw if entry is not root_entry]

    # Запись принимается только если её подписал уже проверенный администратор.
    # Это не позволяет подложить свой ключ и подписать им фиктивного админа.
    progress = True
    while pending and progress:
        progress = False
        for entry in pending[:]:
            fp16 = entry.get("fp16")
            signer = entry.get("added_by")
            if (
                not isinstance(fp16, str)
                or not re.fullmatch(r"[0-9a-fA-F]{16}", fp16)
                or not isinstance(signer, str)
                or signer not in verified_fps
            ):
                continue
            try:
                by_pub = load_pub_key_by_fp16(shared_folder, signer)
            except (FileNotFoundError, ValueError):
                continue
            if verify_signature(entry, by_pub):
                verified.append(entry)
                verified_fps.add(fp16)
                pending.remove(entry)
                progress = True

    for entry in pending:
        logger.warning(
            f"Админ {entry.get('fp16', '?')}: нет доверенной цепочки подписи; запись пропущена"
        )
    return verified


def has_any_admin(shared_folder: Path | str) -> bool:
    return bool(load_admins_verified(shared_folder))


def is_admin(shared_folder: Path | str, fp16: str) -> bool:
    return any(a["fp16"] == fp16 for a in load_admins_verified(shared_folder))


def is_super(shared_folder: Path | str, fp16: str) -> bool:
    return any(
        a["fp16"] == fp16 and a.get("is_super") is True
        for a in load_admins_verified(shared_folder)
    )


def get_super(shared_folder: Path | str) -> dict | None:
    return next(
        (a for a in load_admins_verified(shared_folder) if a.get("is_super") is True),
        None,
    )


def _validate_entry(entry: dict) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("fp16"), str)
        and re.fullmatch(r"[0-9a-fA-F]{16}", entry["fp16"]) is not None
        and type(entry.get("added_at")) is int
        and entry["added_at"] > 0
        and isinstance(entry.get("added_by"), str)
        and re.fullmatch(r"[0-9a-fA-F]{16}", entry["added_by"]) is not None
        and type(entry.get("is_super")) is bool
        and type(entry.get("can_manage_admins")) is bool
        and type(entry.get("can_read_all_chats")) is bool
        and type(entry.get("can_grant_delete_rights")) is bool
    )


def _assert_private_key_matches(
    shared_folder: Path | str, fp16: str, private_pem: str
) -> None:
    public_pem = load_pub_key_by_fp16(shared_folder, fp16)
    probe = b"pygram-admin-key-pair-check"
    signature = rsa_sign(private_pem, probe)
    if not rsa_verify(public_pem, probe, signature):
        raise ValueError(
            "Приватный ключ не соответствует публичному ключу администратора"
        )


def _make_entry(fp16: str, by: str, is_super_new: bool, by_priv: str) -> dict:
    entry = {
        "fp16": fp16,
        "added_at": int(time.time() * 1000),
        "added_by": by,
        "is_super": is_super_new,
        "can_manage_admins": False,
        "can_read_all_chats": False,
        "can_grant_delete_rights": False,
    }
    entry["signature"] = to_base64(rsa_sign(by_priv, admin_signature_payload(entry)))
    return entry


def make_admin(
    shared_folder: Path | str,
    fp16: str,
    by: str,
    by_priv: str | None = None,
    *,
    bootstrap: bool = False,
) -> None:
    """Назначает админа. Первый root создаётся только явным bootstrap=True."""
    ensure_shared_structure(shared_folder)
    if not bootstrap and by == "system":
        raise ValueError(
            "Небезопасное назначение by='system' запрещено. Используйте bootstrap=True только для первого аккаунта."
        )
    data = _load_list(shared_folder)
    raw = data["admins"]
    if not isinstance(fp16, str) or not re.fullmatch(r"[0-9a-fA-F]{16}", fp16):
        raise ValueError("Некорректный fingerprint администратора")
    if any(a.get("fp16") == fp16 for a in raw):
        raise ValueError(f"{fp16} уже админ")
    try:
        target_pub = load_pub_key_by_fp16(shared_folder, fp16)
        if not fingerprint(target_pub).startswith(fp16.lower()):
            raise ValueError("Публичный ключ не соответствует fingerprint пользователя")
    except FileNotFoundError as exc:
        raise ValueError("Публичный ключ нового администратора не найден") from exc

    if bootstrap:
        if raw:
            raise ValueError(
                "Первого супер-администратора можно создать только в пустой системе"
            )
        if by != fp16:
            raise ValueError(
                "Первый супер-администратор должен подписать собственную запись"
            )
        if by_priv is None:
            raise ValueError(
                "by_priv обязателен для создания первого супер-администратора"
            )
        _assert_private_key_matches(shared_folder, fp16, by_priv)
        entry = _make_entry(fp16, fp16, True, by_priv)
    else:
        if by == "system":
            raise ValueError(
                "Небезопасное назначение by='system' запрещено. Используйте bootstrap=True только для первого аккаунта."
            )
        admins = load_admins_verified(shared_folder)
        by_entry = next((a for a in admins if a["fp16"] == by), None)
        if not by_entry:
            raise ValueError("Вы не админ")
        if not by_entry.get("is_super", False) and not by_entry.get(
            "can_manage_admins", False
        ):
            raise ValueError("У вас нет прав на назначение админов")
        if by_priv is None:
            raise ValueError("by_priv обязателен")
        _assert_private_key_matches(shared_folder, by, by_priv)
        entry = _make_entry(fp16, by, False, by_priv)

    data["admins"].append(entry)
    _save_list(shared_folder, data)
    logger.info(f"Админ назначен: {fp16} (by={by})")


def remove_admin(
    shared_folder: Path | str,
    fp16: str,
    by: str,
    by_priv: str | None = None,
) -> None:
    """Снимает админа. Супер-админа снять нельзя."""

    admins = load_admins_verified(shared_folder)

    # Целевой администратор должен пройти проверку доверия.
    verified_target = next(
        (a for a in admins if a["fp16"] == fp16),
        None,
    )

    if verified_target is None:
        raise ValueError(f"{fp16} не является проверенным администратором")

    if verified_target.get("is_super"):
        raise ValueError("Нельзя снять супер-админа")

    # Проверяем права инициатора.
    by_entry = next(
        (a for a in admins if a["fp16"] == by),
        None,
    )

    if not by_entry:
        raise ValueError("Вы не админ")

    if not by_entry.get("is_super") and not by_entry.get("can_manage_admins"):
        raise ValueError("У вас нет прав на снятие админов")

    if by_priv is None:
        raise ValueError("by_priv обязателен")

    # Проверяем соответствие приватного ключа инициатору.
    by_pub = load_pub_key_by_fp16(shared_folder, by)
    probe = rsa_sign(by_priv, b"pygram-admin-action-check")

    if not rsa_verify(by_pub, b"pygram-admin-action-check", probe):
        raise ValueError("Приватный ключ не соответствует текущему администратору")

    # Повторно читаем список и убеждаемся, что запись не изменилась.
    data = _load_list(shared_folder)

    target = next(
        (a for a in data["admins"] if a.get("fp16") == fp16),
        None,
    )

    if target is None:
        raise ValueError(f"{fp16} не админ")

    if target != verified_target:
        raise ValueError("Запись администратора изменилась во время операции")

    data["admins"] = [a for a in data["admins"] if a.get("fp16") != fp16]

    _save_list(shared_folder, data)
    logger.info(f"Админ снят: {fp16} (by={by})")


def _change_right(
    shared_folder: Path | str,
    fp16: str,
    by: str,
    by_priv: str,
    field: str,
) -> None:
    admins = load_admins_verified(shared_folder)

    by_entry = next((a for a in admins if a["fp16"] == by), None)
    if not by_entry or not by_entry.get("is_super", False):
        raise ValueError("Только супер-админ может менять права")

    by_pub = load_pub_key_by_fp16(shared_folder, by)
    probe = rsa_sign(by_priv, b"pygram-admin-action-check")
    if not rsa_verify(by_pub, b"pygram-admin-action-check", probe):
        raise ValueError("Приватный ключ не соответствует супер-администратору")

    # Изменять можно только запись, прошедшую проверку цепочки доверия.
    verified_target = next(
        (a for a in admins if a.get("fp16") == fp16),
        None,
    )
    if verified_target is None:
        raise ValueError(f"{fp16} не является проверенным администратором")

    data = _load_list(shared_folder)
    target = next(
        (a for a in data["admins"] if a.get("fp16") == fp16),
        None,
    )

    if target is None:
        raise ValueError(f"{fp16} не админ")

    # Проверяем, что запись не изменилась после проверки доверия.
    if target != verified_target:
        raise ValueError("Запись администратора изменилась во время операции")

    target[field] = not target.get(field, False)

    # Изменение привилегий переподписывается супер-администратором.
    target["added_by"] = by
    target["signature"] = to_base64(rsa_sign(by_priv, admin_signature_payload(target)))

    _save_list(shared_folder, data)


def toggle_manage_rights(
    shared_folder: Path | str, fp16: str, by: str, by_priv: str
) -> None:
    _change_right(shared_folder, fp16, by, by_priv, "can_manage_admins")


def toggle_read_rights(
    shared_folder: Path | str, fp16: str, by: str, by_priv: str
) -> None:
    _change_right(shared_folder, fp16, by, by_priv, "can_read_all_chats")


def toggle_grant_delete_rights(
    shared_folder: Path | str, fp16: str, by: str, by_priv: str
) -> None:
    """Разрешает или запрещает администратору выдавать права удаления чужих сообщений."""
    _change_right(
        shared_folder,
        fp16,
        by,
        by_priv,
        "can_grant_delete_rights",
    )


def can_read_all_chats(shared_folder: Path | str, fp16: str) -> bool:
    if is_super(shared_folder, fp16):
        return True
    entry = next(
        (a for a in load_admins_verified(shared_folder) if a["fp16"] == fp16), None
    )
    return bool(entry and entry.get("can_read_all_chats"))


def can_manage_admins(shared_folder: Path | str, fp16: str) -> bool:
    if is_super(shared_folder, fp16):
        return True
    entry = next(
        (a for a in load_admins_verified(shared_folder) if a["fp16"] == fp16), None
    )
    return bool(entry and entry.get("can_manage_admins"))


def verify_signature(entry: dict, by_pub_pem: str) -> bool:
    """Проверяет подпись всех значимых полей записи администратора."""
    if not _validate_entry(entry) or not entry.get("signature"):
        return False
    try:
        signature = from_base64(entry["signature"])
        return rsa_verify(by_pub_pem, admin_signature_payload(entry), signature)
    except (ValueError, TypeError, KeyError):
        return False
