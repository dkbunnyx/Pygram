"""Виджет списка чатов Pygram."""

from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget,
    QListWidgetItem, QPushButton
)
from PySide6.QtCore import Qt, Signal
from loguru import logger

from src.core.chat_logic import list_user_chats, create_favorites


class ChatListWidget(QWidget):
    """Список чатов пользователя."""

    chat_selected = Signal(str)

    def __init__(self, shared_folder: str | Path, user_fp16: str, user_login: str, parent=None):
        super().__init__(parent)
        self.shared_folder = shared_folder
        self.user_fp16 = user_fp16
        self.user_login = user_login  # <--- СОХРАНЯЕМ
        self._setup_ui()
        self.refresh_chats()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Кнопка создания чата
        self.btn_new_chat = QPushButton("+ Новый чат")
        self.btn_new_chat.setCursor(Qt.PointingHandCursor)
        self.btn_new_chat.clicked.connect(self._on_new_chat_clicked)
        layout.addWidget(self.btn_new_chat)

        # Список чатов
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("chat_list")
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list_widget)

    def refresh_chats(self):
        self.list_widget.clear()
        try:
            chats = list_user_chats(self.shared_folder, self.user_fp16)

            if not chats:
                item = QListWidgetItem("Нет чатов. Создайте новый!")
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                self.list_widget.addItem(item)
                return

            for chat in chats:
                chat_id = chat["chat_id"]
                chat_type = chat["type"]

                if chat_type == "dm":
                    icon = "👤"
                    display_name = "Личный чат"
                elif chat_type == "group":
                    icon = "👥"
                    display_name = f"Группа {chat_id[4:12]}"
                elif chat_type == "favorites":
                    icon = "⭐"
                    display_name = "Избранное"
                elif chat_type == "admin_chat":
                    icon = "🛡"
                    display_name = "Админ-чат"
                else:
                    icon = "💬"
                    display_name = chat_id

                text = f"{icon}  {display_name}"
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, chat_id)

                self.list_widget.addItem(item)

        except Exception as e:
            logger.error(f"Ошибка загрузки чатов: {e}")
            item = QListWidgetItem("Ошибка загрузки чатов")
            self.list_widget.addItem(item)

    def _on_item_clicked(self, item: QListWidgetItem):
        chat_id = item.data(Qt.UserRole)
        if chat_id:
            self.chat_selected.emit(chat_id)

    def _on_new_chat_clicked(self):
        try:
            # Передаем ЛОГИН, а не fp16
            create_favorites(self.shared_folder, self.user_login)
            self.refresh_chats()
            logger.info("Создано Избранное")
        except Exception as e:
            logger.error(f"Ошибка создания чата: {e}")