"""Виджет окна чата Pygram."""

from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTextBrowser, QLineEdit, QPushButton, QLabel
)
from PySide6.QtCore import Qt
from loguru import logger

from src.core.message import read_messages, send_message
from src.core.chat_logic import get_chat_meta
from src.storage.local_db import LocalDB


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

        self.input_widget = QWidget()
        self.input_widget.setFixedHeight(60)

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

        self.input_widget.setVisible(False)
        self.text_browser.setHtml("<i style='color: gray;'>Выберите чат слева, чтобы начать переписку</i>")

    def load_chat(self, chat_id: str):
        self.current_chat_id = chat_id
        self.text_browser.clear()

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

            # --- ОПРЕДЕЛЯЕМ ЦВЕТА ---
            db = LocalDB()
            theme = db.get_setting("theme", "base")

            if theme == "custom":
                bg_my = db.get_setting("color_my_msg", "#4a90e2")
                bg_other = db.get_setting("color_other_msg", "#e2a04a")
                text_color_my = "#ffffff"
                text_color_other = "#ffffff"
                name_color = "#ffffff"

                chat_bg = db.get_setting("color_chat_bg", "#1a1a2e")
                self.text_browser.setStyleSheet(f"QTextBrowser {{ background-color: {chat_bg}; border: none; }}")
            else:
                # Для основной темы (base)
                bg_my = "#2b2b3d"
                bg_other = "#252538"
                text_color_my = "#ffffff"
                text_color_other = "#cdd6f4"
                name_color = "#89b4fa"
                self.text_browser.setStyleSheet("")

            html = ""
            for msg in messages:
                is_me = (msg.sender_fp16 == self.user.fp16)
                align = "right" if is_me else "left"

                bg_color = bg_my if is_me else bg_other
                txt_color = text_color_my if is_me else text_color_other

                sender_name = "Вы" if is_me else db.get_login_by_fp16(msg.sender_fp16)

                html += f"""
                <div style="text-align: {align}; margin-top: 10px; margin-bottom: 10px;">
                    <div style="color: {name_color}; font-weight: bold; font-size: 11px; margin-bottom: 2px;">
                        {sender_name}
                    </div>
                    <table align="{align}" cellpadding="8" cellspacing="0" style="background-color: {bg_color}; border-radius: 8px; color: {txt_color}; font-size: 14px;">
                        <tr>
                            <td>{msg.text}</td>
                        </tr>
                    </table>
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