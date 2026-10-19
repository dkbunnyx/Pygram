"""Виджет списка чатов Pygram."""

from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget,
    QListWidgetItem, QPushButton, QInputDialog, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from loguru import logger

from src.core.chat_logic import list_user_chats, create_dm_chat, list_all_chats
from src.storage.local_db import LocalDB


class ChatListWidget(QWidget):
    """Список чатов пользователя."""

    chat_selected = Signal(str)

    def __init__(self, shared_folder: str | Path, user_fp16: str, user_login: str, user_is_admin: bool = False, parent=None):
        super().__init__(parent)
        self.shared_folder = shared_folder
        self.user_fp16 = user_fp16
        self.user_login = user_login
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

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("chat_list")
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list_widget)

    def refresh_chats(self):
        self.list_widget.clear()
        try:
            # 1. МОИ ЧАТЫ
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

            # 2. ВСЕ ЧАТЫ (Только для админов)
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
            other_fp = parts[0] if parts[1] == self.user_fp16 else parts[1]
            display_name = db.get_login_by_fp16(other_fp)
            if display_name == other_fp[:8]:
                display_name = f"Чат {chat_id[3:10]}"

        elif chat_type == "group":
            icon = "👥"
            display_name = f"Группа {chat_id[4:12]}"
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
                self.refresh_chats()

                for i in range(self.list_widget.count()):
                    item = self.list_widget.item(i)
                    if item.data(Qt.UserRole) == chat_id:
                        self.list_widget.setCurrentItem(item)
                        self.chat_selected.emit(chat_id)
                        break
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", str(e))