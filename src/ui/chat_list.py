"""Виджет списка чатов Pygram."""

from pathlib import Path
import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget,
    QListWidgetItem, QPushButton, QInputDialog, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from loguru import logger

from src.core.chat_logic import list_user_chats, create_dm_chat, list_all_chats, create_group_chat
from src.storage.local_db import LocalDB
from src.core.crypto import unwrap_key, aes_decrypt, from_base64
from src.storage.shared_store import load_chat_keys, load_chat_meta_enc


class ChatListWidget(QWidget):
    """Список чатов пользователя."""

    chat_selected = Signal(str)

    def __init__(self, shared_folder: str | Path, user_fp16: str, user_login: str, user_priv_pem: str = "", user_is_admin: bool = False, parent=None):
        super().__init__(parent)
        self.shared_folder = shared_folder
        self.user_fp16 = user_fp16
        self.user_login = user_login
        self.user_priv_pem = user_priv_pem
        self.user_is_admin = user_is_admin
        self._setup_ui()
        self.refresh_chats()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.btn_new_chat = QPushButton("+ Новый чат")
        self.btn_new_chat.setCursor(Qt.PointingHandCursor)
        self.btn_new_chat.clicked.connect(self._on_new_chat_clicked)
        layout.addWidget(self.btn_new_chat)

        self.btn_new_group = QPushButton("+ Новая группа")
        self.btn_new_group.setCursor(Qt.PointingHandCursor)
        self.btn_new_group.clicked.connect(self._on_new_group_clicked)
        layout.addWidget(self.btn_new_group)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("chat_list")
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list_widget)

    def _get_group_name(self, chat_id: str) -> str:
        """Пытается расшифровать название группы."""
        if not self.user_priv_pem:
            return f"Группа {chat_id[4:12]}"
        try:
            keys = load_chat_keys(self.shared_folder, chat_id)
            wrapped = keys.get("wrapped", {})
            if self.user_fp16 in wrapped:
                group_key = unwrap_key(wrapped, self.user_fp16, self.user_priv_pem)
                enc = load_chat_meta_enc(self.shared_folder, chat_id)
                data = json.loads(enc.decode("utf-8"))

                if "nonce" in data and "ciphertext" in data:
                    aad = f"chat_id={chat_id}|meta".encode("utf-8")
                    decrypted = aes_decrypt(group_key, from_base64(data["nonce"]), from_base64(data["ciphertext"]), aad=aad)
                    meta = json.loads(decrypted.decode("utf-8"))
                    return meta.get("name", f"Группа {chat_id[4:12]}")
        except Exception as e:
            logger.error(f"Не удалось расшифровать имя группы {chat_id}: {e}")
        return f"Группа {chat_id[4:12]}"

    def refresh_chats(self):
        self.list_widget.clear()
        try:
            header_my = QListWidgetItem("МОИ ЧАТЫ")
            header_my.setFlags(Qt.NoItemFlags)
            header_my.setForeground(QColor("gray"))
            self.list_widget.addItem(header_my)

            chats = list_user_chats(self.shared_folder, self.user_fp16)
            if not chats:
                item = QListWidgetItem("  Нет чатов")
                item.setFlags(Qt.NoItemFlags)
                self.list_widget.addItem(item)
            else:
                for chat in chats:
                    self._add_chat_item(chat)

            if self.user_is_admin:
                header_all = QListWidgetItem("СПИСОК ВСЕХ ЧАТОВ (АДМИН)")
                header_all.setFlags(Qt.NoItemFlags)
                header_all.setForeground(QColor("gray"))
                self.list_widget.addItem(header_all)

                all_chats = list_all_chats(self.shared_folder)
                my_chat_ids = [c["chat_id"] for c in chats]

                for chat in all_chats:
                    if chat["chat_id"] not in my_chat_ids:
                        self._add_chat_item(chat, prefix="  ")

        except Exception as e:
            logger.error(f"Ошибка загрузки чатов: {e}")

    def _add_chat_item(self, chat: dict, prefix: str = ""):
        chat_id = chat["chat_id"]
        chat_type = chat["type"]
        db = LocalDB()

        if chat_type == "dm":
            icon = "👤"
            parts = chat_id.replace("dm_", "").split("__")
            if len(parts) == 2:
                fp1, fp2 = parts
                if fp1 == self.user_fp16:
                    other_fp = fp2
                elif fp2 == self.user_fp16:
                    other_fp = fp1
                else:
                    other_fp = fp1

                # Пытаемся получить логин из БД
                display_name = db.get_login_by_fp16(other_fp)

                # Если логин не найден (вернулся fp16), то пробуем взять оригинальное имя
                # (но в шаре его нет, поэтому оставляем fp16)
                if display_name == other_fp[:8]:
                    display_name = f"Чат {other_fp[:8]}"
            else:
                display_name = "Личный чат"

        elif chat_type == "group":
            icon = "👥"
            display_name = self._get_group_name(chat_id)

        elif chat_type == "favorites":
            icon = "⭐"
            owner_fp = chat_id.replace("fav_", "")
            owner_name = db.get_login_by_fp16(owner_fp)
            display_name = f"Избранное ({owner_name})" if prefix else "Избранное"
        elif chat_type == "admin_chat":
            icon = "🛡"
            display_name = "Админ-чат"
        else:
            icon = "💬"
            display_name = chat_id

        text = f"{prefix}{icon}  {display_name}"
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, chat_id)
        self.list_widget.addItem(item)

    def _on_item_clicked(self, item: QListWidgetItem):
        chat_id = item.data(Qt.UserRole)
        if chat_id:
            self.chat_selected.emit(chat_id)

    def _on_new_chat_clicked(self):
        login, ok = QInputDialog.getText(self, "Новый чат", "Введите логин пользователя:")
        if ok and login.strip():
            login = login.strip().lower()
            try:
                chat_id = create_dm_chat(self.shared_folder, self.user_login, login)

                # СОХРАНЯЕМ ЛОГИН В БД, чтобы потом отображать его
                from src.core.identity import get_fp16
                other_fp = get_fp16(self.shared_folder, login)
                if other_fp:
                    db = LocalDB()
                    db.save_user_map(other_fp, login)

                self.refresh_chats()

                for i in range(self.list_widget.count()):
                    item = self.list_widget.item(i)
                    if item.data(Qt.UserRole) == chat_id:
                        self.list_widget.setCurrentItem(item)
                        self.chat_selected.emit(chat_id)
                        break
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", str(e))

    def _on_new_group_clicked(self):
        name, ok = QInputDialog.getText(self, "Новая группа", "Введите название группы:")
        if not ok or not name.strip():
            return
        name = name.strip()

        users_str, ok = QInputDialog.getText(
            self, "Участники",
            "Введите логины участников через запятую (например: petya, kolya):"
        )
        if not ok or not users_str.strip():
            return

        member_logins = [u.strip().lower() for u in users_str.split(",") if u.strip()]

        if self.user_login in member_logins:
            member_logins.remove(self.user_login)

        if len(member_logins) < 2:
            QMessageBox.warning(self, "Ошибка", "Нужно минимум 2 других участника (всего 3 с вами).")
            return

        try:
            chat_id = create_group_chat(
                self.shared_folder,
                self.user_login,
                name,
                member_logins
            )
            self.refresh_chats()

            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                if item.data(Qt.UserRole) == chat_id:
                    self.list_widget.setCurrentItem(item)
                    self.chat_selected.emit(chat_id)
                    break
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", str(e))