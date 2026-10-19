"""Виджет окна чата Pygram."""

from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTextBrowser, QLineEdit, QPushButton, QLabel
)
from PySide6.QtCore import Qt
from loguru import logger
from src.storage.local_db import LocalDB
from src.core.message import read_messages, send_message
from src.core.chat_logic import get_chat_meta


class ChatViewWidget(QWidget):
    """Окно с историей сообщений и полем ввода."""

    def __init__(self, shared_folder: str | Path, user, parent=None):
        super().__init__(parent)
        self.shared_folder = shared_folder
        self.user = user
        self.current_chat_id = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.label_title = QLabel("Выберите чат")
        self.label_title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px;")
        layout.addWidget(self.label_title)

        self.text_browser = QTextBrowser()
        self.text_browser.setObjectName("message_history")
        self.text_browser.setOpenExternalLinks(True)
        layout.addWidget(self.text_browser)

        # Панель ввода (скрыта по умолчанию)
        self.input_widget = QWidget()
        input_layout = QHBoxLayout(self.input_widget)
        input_layout.setContentsMargins(0, 0, 0, 0)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Введите сообщение...")
        self.input_field.returnPressed.connect(self._on_send_clicked)
        input_layout.addWidget(self.input_field)

        self.btn_send = QPushButton("Отправить")
        self.btn_send.clicked.connect(self._on_send_clicked)
        input_layout.addWidget(self.btn_send)

        layout.addWidget(self.input_widget)

        # Скрываем панель, пока чат не выбран
        self.input_widget.setVisible(False)
        self.text_browser.setHtml("<i style='color: gray;'>Выберите чат слева, чтобы начать переписку</i>")

    def load_chat(self, chat_id: str):
        self.current_chat_id = chat_id
        self.text_browser.clear()

        # Показываем панель ввода, так как чат выбран
        self.input_widget.setVisible(True)

        try:
            meta = get_chat_meta(self.shared_folder, chat_id)
            chat_type = meta["type"]

            if chat_type == "dm":
                title = "👤 Личный чат"
            elif chat_type == "group":
                title = f"👥 Группа {chat_id[4:12]}"
            elif chat_type == "favorites":
                title = "⭐ Избранное"
            elif chat_type == "admin_chat":
                title = "🛡 Админ-чат"
            else:
                title = chat_id

            self.label_title.setText(title)

            messages = read_messages(
                self.shared_folder, chat_id,
                self.user.fp16, self.user.priv_pem
            )

            if not messages:
                self.text_browser.setHtml("<i>Нет сообщений. Напишите первым!</i>")
                return

            db = LocalDB()

            html = ""
            for msg in messages:
                is_me = (msg.sender_fp16 == self.user.fp16)
                color = "#4a90e2" if is_me else "#e2a04a"
                align = "right" if is_me else "left"

                # Получаем логин из БД
                sender_name = "Вы" if is_me else db.get_login_by_fp16(msg.sender_fp16)

                html += f"""
                           <div style="text-align: {align}; margin: 5px;">
                               <span style="color: {color}; font-weight: bold;">{sender_name}</span>
                               <br>
                               <span style="background: #2a2a2a; padding: 5px 10px; border-radius: 10px; display: inline-block;">
                                   {msg.text}
                               </span>
                           </div>
                           """

            self.text_browser.setHtml(html)
            self.text_browser.verticalScrollBar().setValue(
                self.text_browser.verticalScrollBar().maximum()
            )

        except Exception as e:
            logger.error(f"Ошибка загрузки чата {chat_id}: {e}")
            self.text_browser.setHtml(f"<b style='color: red;'>Ошибка загрузки сообщений</b><br>{e}")

    def _on_send_clicked(self):
        if not self.current_chat_id:
            return

        text = self.input_field.text().strip()
        if not text:
            return

        try:
            send_message(
                self.shared_folder, self.current_chat_id,
                self.user.fp16, self.user.priv_pem, text
            )
            self.input_field.clear()
            self.load_chat(self.current_chat_id)

        except Exception as e:
            logger.error(f"Ошибка отправки сообщения: {e}")