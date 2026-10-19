"""Виджет окна чата Pygram."""

from pathlib import Path
import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QDialog,
    QTextBrowser, QLineEdit, QPushButton, QLabel, QFileDialog
)
from PySide6.QtCore import Qt, QUrl, QEvent
from PySide6.QtGui import QDesktopServices, QKeySequence, QPixmap, QGuiApplication
from loguru import logger
import os
import tempfile
import shutil
import sys

from src.core.message import read_messages, send_message, send_file
from src.core.chat_logic import get_chat_meta
from src.core.crypto import unwrap_key, aes_decrypt, from_base64
from src.storage.local_db import LocalDB
from src.storage.shared_store import chat_files_dir, load_chat_keys, load_chat_meta_enc


class ImageConfirmDialog(QDialog):
    """Диалог подтверждения отправки картинки из буфера."""
    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Отправить картинку?")
        self.resize(400, 300)

        layout = QVBoxLayout(self)

        label = QLabel()
        pixmap = QPixmap.fromImage(image)
        pixmap = pixmap.scaled(380, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        label.setPixmap(pixmap)
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

        btn_layout = QHBoxLayout()

        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_layout.addStretch()

        btn_send = QPushButton("Отправить")
        btn_send.setStyleSheet("background-color: #4a90e2; color: white; font-weight: bold;")
        btn_send.clicked.connect(self.accept)
        btn_layout.addWidget(btn_send)

        layout.addLayout(btn_layout)


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
        self.text_browser.setOpenExternalLinks(False)
        self.text_browser.setOpenLinks(False)
        self.text_browser.anchorClicked.connect(self._on_anchor_clicked)
        layout.addWidget(self.text_browser)

        self.input_widget = QWidget()
        self.input_widget.setFixedHeight(60)

        input_layout = QHBoxLayout(self.input_widget)
        input_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_attach = QPushButton("📎")
        self.btn_attach.setFixedSize(40, 40)
        self.btn_attach.setCursor(Qt.PointingHandCursor)
        self.btn_attach.clicked.connect(self._on_attach_clicked)
        input_layout.addWidget(self.btn_attach)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Введите сообщение...")
        self.input_field.returnPressed.connect(self._on_send_clicked)
        self.input_field.installEventFilter(self)
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

            db = LocalDB()

            # --- ОПРЕДЕЛЯЕМ ЗАГОЛОВОК ---
            if chat_type == "dm":
                parts = chat_id.replace("dm_", "").split("__")
                if len(parts) == 2:
                    fp1, fp2 = parts
                    other_fp = fp1 if fp2 == self.user.fp16 else fp2
                    other_login = db.get_login_by_fp16(other_fp)
                    title = f"👤 {other_login}"
                else:
                    title = "👤 Личный чат"

            elif chat_type == "group":
                group_name = f"Группа {chat_id[4:12]}"
                try:
                    keys = load_chat_keys(self.shared_folder, chat_id)
                    wrapped = keys.get("wrapped", {})
                    if self.user.fp16 in wrapped:
                        group_key = unwrap_key(wrapped, self.user.fp16, self.user.priv_pem)
                        enc = load_chat_meta_enc(self.shared_folder, chat_id)
                        data = json.loads(enc.decode("utf-8"))

                        if "nonce" in data and "ciphertext" in data:
                            aad = f"chat_id={chat_id}|meta".encode("utf-8")
                            decrypted = aes_decrypt(group_key, from_base64(data["nonce"]), from_base64(data["ciphertext"]), aad=aad)
                            meta_group = json.loads(decrypted.decode("utf-8"))
                            group_name = meta_group.get("name", group_name)
                except Exception as e:
                    logger.error(f"Не удалось расшифровать имя группы в chat_view: {e}")

                title = f"👥 {group_name}"

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

                # Обработка файлов
                display_text = msg.text
                if msg.text.startswith("[FILE]") and msg.text.endswith("[/FILE]"):
                    inner = msg.text[6:-7]
                    if "|" in inner:
                        stored_name, display_name = inner.split("|", 1)
                    else:
                        stored_name = display_name = inner

                    file_path = chat_files_dir(self.shared_folder, chat_id) / stored_name
                    ext = display_name.lower().split('.')[-1]

                    if ext in ('png', 'jpg', 'jpeg', 'gif', 'bmp'):
                        file_url = QUrl.fromLocalFile(str(file_path)).toString()
                        display_text = f"""
                        <div style="text-align: center;">
                            <a href='{file_url}'>
                                <img src='{file_url}' style='max-width: 250px; max-height: 250px; border-radius: 5px;' />
                            </a>
                        </div>
                        """
                    else:
                        file_url = QUrl.fromLocalFile(str(file_path)).toString()
                        display_text = f"📎 <a href='{file_url}' style='color: #89b4fa; text-decoration: none;'>📥 {display_name}</a>"

                html += f"""
                <div style="text-align: {align}; margin-top: 10px; margin-bottom: 10px;">
                    <div style="color: {name_color}; font-weight: bold; font-size: 11px; margin-bottom: 2px;">
                        {sender_name}
                    </div>
                    <table align="{align}" cellpadding="8" cellspacing="0" style="background-color: {bg_color}; border-radius: 8px; color: {txt_color}; font-size: 14px;">
                        <tr>
                            <td>{display_text}</td>
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

    def eventFilter(self, obj, event):
        if obj is self.input_field and event.type() == QEvent.KeyPress:
            if event.matches(QKeySequence.Paste):
                clipboard = QGuiApplication.clipboard()
                if clipboard.mimeData().hasImage():
                    image = clipboard.image()
                    if not image.isNull():
                        dialog = ImageConfirmDialog(image, self)
                        if dialog.exec() == QDialog.Accepted:
                            temp_dir = Path(tempfile.gettempdir())
                            temp_path = temp_dir / "pygram_clipboard.png"
                            image.save(str(temp_path), "PNG")

                            try:
                                send_file(
                                    self.shared_folder, self.current_chat_id,
                                    self.user.fp16, self.user.priv_pem, temp_path
                                )
                                self.load_chat(self.current_chat_id)
                            except Exception as e:
                                logger.error(f"Ошибка отправки скриншота: {e}")

                            temp_path.unlink(missing_ok=True)
                        return True
        return super().eventFilter(obj, event)

    def _on_anchor_clicked(self, url: QUrl):
        """Скачивает файл и открывает его."""
        path_str = url.toLocalFile()
        if not path_str:
            return

        src_path = Path(path_str)
        if not src_path.exists():
            return

        if getattr(sys, "frozen", False):
            base_dir = Path(sys.executable).parent
        else:
            base_dir = Path(__file__).resolve().parent.parent.parent

        download_dir = base_dir / "Downloads"

        try:
            download_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            download_dir = Path.home() / "Downloads" / "Pygram"
            download_dir.mkdir(parents=True, exist_ok=True)

        stored_name = src_path.name
        if "_" in stored_name:
            display_name = stored_name.split("_", 1)[1]
        else:
            display_name = stored_name

        dest_path = download_dir / display_name

        try:
            if not dest_path.exists():
                shutil.copy2(src_path, dest_path)

            os.startfile(str(dest_path))
        except Exception as e:
            logger.error(f"Ошибка скачивания файла: {e}")

    def _on_attach_clicked(self):
        if not self.current_chat_id:
            return

        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите файл")
        if file_path:
            try:
                send_file(
                    self.shared_folder, self.current_chat_id,
                    self.user.fp16, self.user.priv_pem, file_path
                )
                self.load_chat(self.current_chat_id)
            except Exception as e:
                logger.error(f"Ошибка отправки файла: {e}")

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