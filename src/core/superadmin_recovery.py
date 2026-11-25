"""Механизм настройки и восстановления супер-администратора Pygram.

Descriptor проверяется по уже закреплённому root key, а сертификат перехода —
по recovery public key, закреплённому локально на каждом компьютере.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from src.core.crypto import (
    aes_decrypt,
    aes_encrypt,
    derive_key_argon2,
    fingerprint,
    from_base64,
    generate_rsa_keypair,
    generate_salt,
    rsa_sign,
    rsa_verify,
    to_base64,
)
from src.storage.shared_store import write_json_atomic

RECOVERY_VERSION = 1
RECOVERY_CERTIFICATE_VERSION = 2
RECOVERY_FILE = "superadmin_recovery.json"
RECOVERY_DESCRIPTOR_FILE = "superadmin_recovery_descriptor.json"
RECOVERY_CERTIFICATE_FILE = "superadmin_recovery_certificate.json"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")
_AAD_PREFIX = b"PYGRAM-SUPERADMIN-RECOVERY-V1\0"


class RecoveryError(ValueError):
    """Ошибка данных или проверки процедуры восстановления."""


def _canonical_json(data: dict[str, Any]) -> bytes:
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _aad(public_fingerprint: str) -> bytes:
    return _AAD_PREFIX + public_fingerprint.encode("ascii")


def create_recovery_material(recovery_password: str) -> tuple[dict, str, dict]:
    """Создаёт recovery keypair и зашифрованный пакет.

    Возвращает (package, recovery_public_pem, descriptor_unsigned).
    Приватный ключ никогда не возвращается в открытом виде.
    """
    if not isinstance(recovery_password, str) or len(recovery_password) < 12:
        raise RecoveryError("Пароль восстановления должен содержать минимум 12 символов.")

    private_pem, public_pem = generate_rsa_keypair()
    public_fp = fingerprint(public_pem).lower()
    salt = generate_salt(16)
    key = derive_key_argon2(recovery_password, salt)
    nonce, ciphertext = aes_encrypt(
        key, private_pem.encode("ascii"), aad=_aad(public_fp)
    )

    package = {
        "version": RECOVERY_VERSION,
        "algorithm": "argon2id-aes-256-gcm",
        "public_fingerprint": public_fp,
        "salt": to_base64(salt),
        "nonce": to_base64(nonce),
        "ciphertext": to_base64(ciphertext),
    }
    descriptor = {
        "version": RECOVERY_VERSION,
        "public_fingerprint": public_fp,
        "public_key": public_pem,
    }
    return package, public_pem, descriptor


def unlock_recovery_private_key(package: dict, recovery_password: str) -> str:
    """Расшифровывает recovery private key; ошибки пароля/целостности единообразны."""
    required = {
        "version", "algorithm", "public_fingerprint", "salt", "nonce", "ciphertext"
    }
    if not isinstance(package, dict) or set(package) != required:
        raise RecoveryError("Повреждён пакет восстановления.")
    if package.get("version") != RECOVERY_VERSION:
        raise RecoveryError("Неподдерживаемая версия пакета восстановления.")
    if package.get("algorithm") != "argon2id-aes-256-gcm":
        raise RecoveryError("Неизвестный алгоритм пакета восстановления.")

    public_fp = package.get("public_fingerprint")
    if not isinstance(public_fp, str) or not _HEX64.fullmatch(public_fp):
        raise RecoveryError("Некорректный fingerprint ключа восстановления.")
    if not isinstance(recovery_password, str) or not recovery_password:
        raise RecoveryError("Введите пароль восстановления.")

    try:
        salt = from_base64(package["salt"])
        nonce = from_base64(package["nonce"])
        ciphertext = from_base64(package["ciphertext"])
        if len(salt) != 16 or len(nonce) != 12 or len(ciphertext) < 17:
            raise ValueError("invalid lengths")
        key = derive_key_argon2(recovery_password, salt)
        private_pem = aes_decrypt(
            key, nonce, ciphertext, aad=_aad(public_fp)
        ).decode("ascii")
    except Exception as exc:
        raise RecoveryError("Неверный пароль восстановления или повреждён пакет.") from exc

    # Проверяем соответствие расшифрованного приватного ключа публичному ключу
    # не здесь: пакет не содержит public PEM. Это делает verify_recovery_pair.
    return private_pem


def verify_recovery_pair(private_pem: str, public_pem: str) -> bool:
    """Проверяет, что приватный и публичный recovery-ключи образуют пару."""
    try:
        probe = b"PYGRAM-RECOVERY-KEY-CHECK-V1"
        signature = rsa_sign(private_pem, probe)
        return rsa_verify(public_pem, probe, signature)
    except Exception:
        return False


def sign_recovery_descriptor(
    descriptor_unsigned: dict, root_private_pem: str
) -> dict:
    """Подписывает привязку recovery public key действующим root-ключом."""
    if not isinstance(descriptor_unsigned, dict) or set(descriptor_unsigned) != {
        "version", "public_fingerprint", "public_key"
    }:
        raise RecoveryError("Некорректное описание ключа восстановления.")
    public_pem = descriptor_unsigned.get("public_key")
    public_fp = descriptor_unsigned.get("public_fingerprint")
    if not isinstance(public_pem, str) or not isinstance(public_fp, str):
        raise RecoveryError("Некорректное описание ключа восстановления.")
    if fingerprint(public_pem).lower() != public_fp.lower():
        raise RecoveryError("Fingerprint recovery public key не совпадает.")
    result = dict(descriptor_unsigned)
    result["signature"] = to_base64(
        rsa_sign(root_private_pem, _canonical_json(descriptor_unsigned))
    )
    return result


def verify_recovery_descriptor(descriptor: dict, trusted_root_public_pem: str) -> dict:
    """Проверяет root-подпись recovery descriptor и возвращает проверенные данные."""
    required = {"version", "public_fingerprint", "public_key", "signature"}
    if not isinstance(descriptor, dict) or set(descriptor) != required:
        raise RecoveryError("Повреждено описание ключа восстановления.")
    unsigned = {key: descriptor[key] for key in ("version", "public_fingerprint", "public_key")}
    if unsigned["version"] != RECOVERY_VERSION:
        raise RecoveryError("Неподдерживаемая версия описания восстановления.")
    public_pem = unsigned["public_key"]
    public_fp = unsigned["public_fingerprint"]
    if not isinstance(public_pem, str) or not isinstance(public_fp, str):
        raise RecoveryError("Некорректный ключ восстановления.")
    if not _HEX64.fullmatch(public_fp) or fingerprint(public_pem).lower() != public_fp:
        raise RecoveryError("Fingerprint ключа восстановления не совпадает.")
    try:
        signature = from_base64(descriptor["signature"])
    except Exception as exc:
        raise RecoveryError("Некорректная подпись описания восстановления.") from exc
    if not rsa_verify(trusted_root_public_pem, _canonical_json(unsigned), signature):
        raise RecoveryError("Подпись описания восстановления недействительна.")
    return {"public_fingerprint": public_fp, "public_key": public_pem}


def build_recovery_certificate(
    recovery_private_pem: str,
    new_root_fp16: str,
    new_root_fingerprint: str,
    old_root_fp16: str,
    old_root_fingerprint: str,
) -> dict:
    """Создаёт сертификат перехода от конкретного старого root к новому."""
    if not isinstance(new_root_fp16, str) or not _HEX16.fullmatch(new_root_fp16.lower()):
        raise RecoveryError("Некорректный fp16 нового супер-администратора.")
    if not isinstance(new_root_fingerprint, str) or not _HEX64.fullmatch(new_root_fingerprint.lower()):
        raise RecoveryError("Некорректный fingerprint нового супер-администратора.")
    fp16 = new_root_fp16.lower()
    full_fp = new_root_fingerprint.lower()
    if not full_fp.startswith(fp16):
        raise RecoveryError("Fingerprint нового root не соответствует fp16.")

    if (
        not isinstance(old_root_fp16, str)
        or not _HEX16.fullmatch(old_root_fp16.lower())
        or not isinstance(old_root_fingerprint, str)
        or not _HEX64.fullmatch(old_root_fingerprint.lower())
        or not old_root_fingerprint.lower().startswith(old_root_fp16.lower())
    ):
        raise RecoveryError("Некорректный fingerprint старого супер-администратора.")

    unsigned = {
        "version": RECOVERY_CERTIFICATE_VERSION,
        "old_root_fp16": old_root_fp16.lower(),
        "old_root_fingerprint": old_root_fingerprint.lower(),
        "new_root_fp16": fp16,
        "new_root_fingerprint": full_fp,
        "issued_at": int(time.time()),
    }
    return {
        **unsigned,
        "signature": to_base64(rsa_sign(recovery_private_pem, _canonical_json(unsigned))),
    }


def verify_recovery_certificate(
    certificate: dict, pinned_recovery_public_pem: str
) -> dict:
    """Проверяет сертификат по recovery public key, полученному из локального pin."""
    required = {
        "version", "old_root_fp16", "old_root_fingerprint",
        "new_root_fp16", "new_root_fingerprint", "issued_at", "signature"
    }
    if not isinstance(certificate, dict) or set(certificate) != required:
        raise RecoveryError("Повреждён сертификат восстановления.")
    unsigned = {key: certificate[key] for key in (
        "version", "old_root_fp16", "old_root_fingerprint",
        "new_root_fp16", "new_root_fingerprint", "issued_at"
    )}
    if type(unsigned["version"]) is not int or unsigned["version"] != RECOVERY_CERTIFICATE_VERSION:
        raise RecoveryError("Неподдерживаемая версия сертификата восстановления.")
    old_fp16 = unsigned["old_root_fp16"]
    old_full_fp = unsigned["old_root_fingerprint"]
    fp16 = unsigned["new_root_fp16"]
    full_fp = unsigned["new_root_fingerprint"]
    issued_at = unsigned["issued_at"]
    if (
        not isinstance(old_fp16, str) or not _HEX16.fullmatch(old_fp16)
        or not isinstance(old_full_fp, str) or not _HEX64.fullmatch(old_full_fp)
        or not old_full_fp.startswith(old_fp16)
    ):
        raise RecoveryError("Некорректный старый root в сертификате восстановления.")
    if not isinstance(fp16, str) or not _HEX16.fullmatch(fp16):
        raise RecoveryError("Некорректный fp16 в сертификате восстановления.")
    if not isinstance(full_fp, str) or not _HEX64.fullmatch(full_fp) or not full_fp.startswith(fp16):
        raise RecoveryError("Некорректный fingerprint в сертификате восстановления.")
    if type(issued_at) is not int or issued_at <= 0 or issued_at > int(time.time()) + 300:
        raise RecoveryError("Некорректная дата сертификата восстановления.")
    try:
        signature = from_base64(certificate["signature"])
    except Exception as exc:
        raise RecoveryError("Некорректная подпись сертификата восстановления.") from exc
    if not rsa_verify(pinned_recovery_public_pem, _canonical_json(unsigned), signature):
        raise RecoveryError("Подпись сертификата восстановления недействительна.")
    return unsigned


def save_recovery_files(shared_folder: str | Path, package: dict, descriptor: dict) -> None:
    """Сохраняет пакет и подписанный descriptor в .admins/ атомарно пофайлово."""
    from src.core.admin import admins_path

    directory = admins_path(shared_folder).parent
    directory.mkdir(parents=True, exist_ok=True)
    write_json_atomic(directory / RECOVERY_FILE, package)
    write_json_atomic(directory / RECOVERY_DESCRIPTOR_FILE, descriptor)


def load_recovery_package(shared_folder: str | Path) -> dict:
    from src.core.admin import admins_path
    path = admins_path(shared_folder).parent / RECOVERY_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("Не удалось прочитать пакет восстановления.") from exc
    if not isinstance(data, dict):
        raise RecoveryError("Повреждён пакет восстановления.")
    return data


def save_recovery_descriptor(shared_folder: str | Path, descriptor: dict) -> None:
    from src.core.admin import admins_path
    directory = admins_path(shared_folder).parent
    directory.mkdir(parents=True, exist_ok=True)
    write_json_atomic(directory / RECOVERY_DESCRIPTOR_FILE, descriptor)


def load_recovery_descriptor(shared_folder: str | Path) -> dict:
    from src.core.admin import admins_path
    path = admins_path(shared_folder).parent / RECOVERY_DESCRIPTOR_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("Не удалось прочитать описание восстановления.") from exc
    if not isinstance(data, dict):
        raise RecoveryError("Повреждено описание восстановления.")
    return data


def save_recovery_certificate(shared_folder: str | Path, certificate: dict) -> None:
    from src.core.admin import admins_path
    directory = admins_path(shared_folder).parent
    directory.mkdir(parents=True, exist_ok=True)
    write_json_atomic(directory / RECOVERY_CERTIFICATE_FILE, certificate)


def load_recovery_certificate(shared_folder: str | Path) -> dict:
    from src.core.admin import admins_path
    path = admins_path(shared_folder).parent / RECOVERY_CERTIFICATE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("Не удалось прочитать сертификат восстановления.") from exc
    if not isinstance(data, dict):
        raise RecoveryError("Повреждён сертификат восстановления.")
    return data


def recover_superadmin(
    shared_folder: str | Path,
    login: str,
    account_password: str,
    recovery_password: str,
):
    """Создаёт нового root и переносит проверенный список администраторов.

    Переписки, группы, сообщения, вложения и пользовательские данные не
    читаются и не изменяются этой функцией.
    """
    from src.core.admin import (
        _load_list,
        _save_list,
        _validate_entry,
        admin_signature_payload,
    )
    from src.core.identity import authenticate, register_identity
    from src.core.trust import _read_pin, pin_recovered_root
    from src.storage.shared_store import load_pub_key_by_fp16, login_exists
    from src.utils.validators import validate_login, validate_password

    try:
        validate_login(login.strip() if isinstance(login, str) else login)
        validate_password(account_password)
    except ValueError as exc:
        raise RecoveryError(str(exc)) from exc

    pin = _read_pin()
    if not pin or not pin.get("recovery_public_key"):
        raise RecoveryError(
            "На этом компьютере не закреплён ключ восстановления. "
            "Автоматическое восстановление небезопасно."
        )

    old_root_fp16 = pin["fp16"]
    try:
        old_root_public = load_pub_key_by_fp16(shared_folder, old_root_fp16)
    except Exception as exc:
        raise RecoveryError("Не найден закреплённый публичный ключ старого root.") from exc
    if fingerprint(old_root_public).lower() != pin["fingerprint"].lower():
        raise RecoveryError("Публичный ключ старого root не совпадает с локальным pin.")

    descriptor = load_recovery_descriptor(shared_folder)
    descriptor_data = verify_recovery_descriptor(descriptor, old_root_public)
    if descriptor_data["public_fingerprint"] != pin["recovery_fingerprint"]:
        raise RecoveryError("Ключ восстановления не совпадает с локально закреплённым.")
    if descriptor_data["public_key"] != pin["recovery_public_key"]:
        raise RecoveryError("Публичный ключ восстановления был подменён.")

    package = load_recovery_package(shared_folder)
    if package.get("public_fingerprint") != pin["recovery_fingerprint"]:
        raise RecoveryError("Пакет восстановления относится к другому ключу.")
    recovery_private = unlock_recovery_private_key(package, recovery_password)
    if not verify_recovery_pair(recovery_private, pin["recovery_public_key"]):
        raise RecoveryError("Пара ключей восстановления не прошла проверку.")

    if not isinstance(login, str) or not login.strip():
        raise RecoveryError("Введите логин нового супер-администратора.")
    if not isinstance(account_password, str) or not account_password:
        raise RecoveryError("Введите пароль нового аккаунта.")
    if login_exists(shared_folder, login.strip()):
        raise RecoveryError("Этот логин уже занят. Выберите другой.")

    # Проверяем прежний roster по закреплённому старому root, не доверяя
    # самому факту нахождения записей в общей папке.
    roster_data = _load_list(shared_folder)
    raw = roster_data["admins"]
    fps = [entry.get("fp16") for entry in raw]
    if len(fps) != len(set(fps)):
        raise RecoveryError("В списке администраторов есть повторяющиеся fingerprint.")

    old_root_entries = [
        entry for entry in raw
        if entry.get("fp16") == old_root_fp16 and entry.get("is_super") is True
    ]
    if len(old_root_entries) > 1:
        raise RecoveryError("В старом списке найдено несколько записей root.")
    for entry in raw:
        if not _validate_entry(entry):
            raise RecoveryError("Список администраторов повреждён; перенос отменён.")
        if entry.get("is_super") and entry.get("fp16") != old_root_fp16:
            raise RecoveryError("В старом списке обнаружен неизвестный супер-администратор.")
    if old_root_entries:
        root_entry = old_root_entries[0]
        if root_entry.get("added_by") != old_root_fp16 or not verify_recovery_admin_signature(
            root_entry, old_root_public
        ):
            raise RecoveryError("Подпись старого супер-администратора недействительна.")

    verified_fps = {old_root_fp16}
    pending = [entry for entry in raw if entry is not (old_root_entries[0] if old_root_entries else None)]
    verified_entries = list(old_root_entries)
    while pending:
        progress = False
        for entry in pending[:]:
            signer_fp = entry.get("added_by")
            if signer_fp not in verified_fps:
                continue
            try:
                signer_public = (
                    old_root_public if signer_fp == old_root_fp16
                    else load_pub_key_by_fp16(shared_folder, signer_fp)
                )
            except Exception as exc:
                raise RecoveryError("Не найден публичный ключ подписанта администратора.") from exc
            if not verify_recovery_admin_signature(entry, signer_public):
                raise RecoveryError(
                    f"Подпись администратора {entry.get('fp16')} недействительна; перенос отменён."
                )
            verified_entries.append(entry)
            verified_fps.add(entry["fp16"])
            pending.remove(entry)
            progress = True
        if not progress:
            raise RecoveryError(
                "Не удалось подтвердить цепочку подписей всех администраторов. "
                "Список не будет изменён."
            )

    # Создаём новый аккаунт только после проверки всей старой цепочки.
    new_fp16 = register_identity(shared_folder, login.strip(), account_password)
    new_root_private, authenticated_fp16 = authenticate(
        shared_folder, login.strip(), account_password
    )
    if authenticated_fp16 != new_fp16:
        raise RecoveryError("Fingerprint нового аккаунта изменился.")
    new_root_public = load_pub_key_by_fp16(shared_folder, new_fp16)
    new_root_full_fp = fingerprint(new_root_public).lower()

    migrated_entries = []
    for old_entry in verified_entries:
        migrated = dict(old_entry)
        # Старый root становится обычным администратором с тем же фактическим
        # набором полномочий, который давала ему роль root.
        if migrated.get("fp16") == old_root_fp16:
            migrated["is_super"] = False
            migrated["can_manage_admins"] = True
            migrated["can_read_all_chats"] = True
            migrated["can_grant_delete_rights"] = True
        migrated["added_by"] = new_fp16
        migrated["signature_version"] = 2
        migrated.pop("signature", None)
        migrated["signature"] = to_base64(
            rsa_sign(new_root_private, admin_signature_payload(migrated))
        )
        migrated_entries.append(migrated)

    if any(entry.get("fp16") == new_fp16 for entry in migrated_entries):
        raise RecoveryError("Новый аккаунт уже присутствует в старом списке администраторов.")

    new_root_entry = {
        "fp16": new_fp16,
        "added_at": int(time.time() * 1000),
        "added_by": new_fp16,
        "is_super": True,
        "can_manage_admins": True,
        "can_read_all_chats": True,
        "can_grant_delete_rights": True,
        "signature_version": 2,
    }
    new_root_entry["signature"] = to_base64(
        rsa_sign(new_root_private, admin_signature_payload(new_root_entry))
    )
    migrated_entries.append(new_root_entry)

    certificate = build_recovery_certificate(
        recovery_private,
        new_fp16,
        new_root_full_fp,
        old_root_fp16,
        pin["fingerprint"],
    )
    new_descriptor = sign_recovery_descriptor(
        {
            "version": RECOVERY_VERSION,
            "public_fingerprint": pin["recovery_fingerprint"],
            "public_key": pin["recovery_public_key"],
        },
        new_root_private,
    )
    # Сначала сертификат, затем новый roster, и только после него descriptor.
    # Если процесс оборвётся до замены roster, старый root и его descriptor
    # останутся согласованными. При обрыве после roster старые клиенты смогут
    # перейти по сертификату, а descriptor будет обновлён при первом входе root.
    save_recovery_certificate(shared_folder, certificate)
    _save_list(shared_folder, {"admins": migrated_entries})
    save_recovery_descriptor(shared_folder, new_descriptor)
    pin_recovered_root(
        new_fp16, new_root_full_fp, pin["recovery_public_key"]
    )

    from src.core.user import login_user
    return login_user(shared_folder, login.strip(), account_password)


def verify_recovery_admin_signature(entry: dict, public_pem: str) -> bool:
    """Локальная обёртка для проверки старых admin-записей."""
    from src.core.admin import verify_signature
    return verify_signature(entry, public_pem)


def setup_recovery_for_current_root(
    shared_folder: str | Path,
    root_fp16: str,
    root_private_pem: str,
    recovery_password: str,
) -> str:
    """Подключает recovery к уже существующему, локально доверенному root."""
    from src.core.trust import _read_pin, _write_pin, require_trusted_root

    root = require_trusted_root(shared_folder)
    if root is None or root["fp16"] != root_fp16:
        raise RecoveryError("Текущий аккаунт не является доверенным супер-администратором.")
    pin = _read_pin()
    if pin and pin.get("recovery_public_key"):
        raise RecoveryError("Ключ восстановления уже закреплён на этом компьютере.")
    if not verify_recovery_pair_from_root(root_private_pem, root["public_key"]):
        raise RecoveryError("Приватный ключ не принадлежит текущему супер-администратору.")

    package, recovery_public, descriptor_unsigned = create_recovery_material(
        recovery_password
    )
    descriptor = sign_recovery_descriptor(descriptor_unsigned, root_private_pem)
    # Не перезаписываем неизвестные recovery-данные: это может быть признаком
    # повреждения или попытки подмены.
    from src.core.admin import admins_path
    directory = admins_path(shared_folder).parent
    if (directory / RECOVERY_FILE).exists() or (directory / RECOVERY_DESCRIPTOR_FILE).exists():
        raise RecoveryError(
            "Файлы восстановления уже существуют, но не совпадают с локальным pin. "
            "Автоматическая перезапись запрещена."
        )
    save_recovery_files(shared_folder, package, descriptor)
    _write_pin(root["fp16"], root["fingerprint"], recovery_public)
    return fingerprint(recovery_public).lower()


def refresh_recovery_descriptor_for_current_root(
    shared_folder: str | Path, root_fp16: str, root_private_pem: str
) -> None:
    """Восстанавливает descriptor после сбоя между заменой roster и descriptor."""
    from src.core.trust import _read_pin, require_trusted_root
    from src.core.admin import admins_path

    pin = _read_pin()
    root = require_trusted_root(shared_folder)
    if (
        not pin or not pin.get("recovery_public_key") or root is None
        or root["fp16"] != root_fp16
    ):
        raise RecoveryError("Нет закреплённого recovery key для текущего root.")
    if not verify_recovery_pair_from_root(root_private_pem, root["public_key"]):
        raise RecoveryError("Приватный ключ не принадлежит текущему root.")
    try:
        current = verify_recovery_descriptor(
            load_recovery_descriptor(shared_folder), root["public_key"]
        )
        if current["public_fingerprint"] == pin["recovery_fingerprint"]:
            return
    except Exception:
        pass
    descriptor = {
        "version": RECOVERY_VERSION,
        "public_fingerprint": pin["recovery_fingerprint"],
        "public_key": pin["recovery_public_key"],
    }
    signed = sign_recovery_descriptor(descriptor, root_private_pem)
    save_recovery_descriptor(shared_folder, signed)


def verify_recovery_pair_from_root(private_pem: str, public_pem: str) -> bool:
    try:
        probe = b"PYGRAM-ROOT-PRIVATE-KEY-CHECK-V1"
        return rsa_verify(public_pem, probe, rsa_sign(private_pem, probe))
    except Exception:
        return False
