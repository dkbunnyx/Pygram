"""Виджет окна чата Pygram (асинхронный + режим выбора сообщений)."""

from pathlib import Path
import json
import os
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QDialog,
    QListWidget, QListWidgetItem, QLineEdit, QPushButton,
    QLabel, QFileDialog, QMessageBox, QMenu
)
from PySide6.QtCore import Qt, QUrl, QEvent, QTimer, QThread, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QPixmap, QGuiApplication, QPainter
from loguru import logger
import tempfile
import time

from src.core.message import (
    read_messages, read_new_messages, send_message, send_file, Message,
)
from src.core.chat_logic import get_chat_meta
from src.core.crypto import unwrap_key, aes_decrypt, from_base64
from src.core.admin import can_read_all_chats
from src.storage.local_db import LocalDB
from src.storage.shared_store import (
    chat_files_dir, chat_message_dir, load_chat_keys, load_chat_meta_enc,
)
from src.core.status import (
    get_status, set_typing, mark_messages_read, get_read_messages,
    set_reaction, get_reactions, delete_message, get_deleted_messages,
)
from src.ui.widgets.emoji_picker import EmojiPicker
from src.ui.widgets.message_widget import MessageWidget


# ============================================================================
# КАСТОМНЫЙ СПИСОК С НЕПОДВИЖНЫМ ФОНОМ
# ============================================================================
class ChatMessagesList(QListWidget):
    """Кастомный QListWidget, который рисует неподвижный фон."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bg_pixmap = None
        self.setStyleSheet("""
            QListWidget { background-color: transparent; border: none; outline: none; }
            QListWidget::item { padding: 0px; margin: 0px; }
            QListWidget::item:selected { background: transparent; }
        """)
        self.setSelectionMode(QListWidget.NoSelection)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)

    def set_background_image(self, image_path: str):
        if image_path and os.path.exists(image_path):
            self.bg_pixmap = QPixmap(image_path)
        else:
            self.bg_pixmap = None
        self.viewport().update()

    def paintEvent(self, event):
        if self.bg_pixmap:
            painter = QPainter(self.viewport())

            # Масштабируем картинку под размер окна (с сохранением пропорций)
            scaled = self.bg_pixmap.scaled(
                self.viewport().size(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation
            )

            # Центрируем
            x = (self.viewport().width() - scaled.width()) // 2
            y = (self.viewport().height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            painter.end()

        super().paintEvent(event)


# ============================================================================
# ФОНОВЫЕ ПОТОКИ
# ============================================================================
class SendWorker(QThread):
    finished = Signal(bool, str, str)

    def __init__(self, shared_folder, chat_id, user_fp16, user_priv_pem, text):
        super().__init__()
        self.shared_folder = shared_folder
        self.chat_id = chat_id
        self.user_fp16 = user_fp16
        self.user_priv_pem = user_priv_pem
        self.text = text

    def run(self):
        try:
            msg_id = send_message(
                self.shared_folder, self.chat_id,
                self.user_fp16, self.user_priv_pem, self.text,
            )
            self.finished.emit(True, "", msg_id)
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")
            self.finished.emit(False, str(e), "")


class ChatLoadWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, shared_folder, chat_id, user_fp16, user_priv_pem, user_login):
        super().__init__()
        self.shared_folder = shared_folder
        self.chat_id = chat_id
        self.user_fp16 = user_fp16
        self.user_priv_pem = user_priv_pem
        self.user_login = user_login

    def run(self):
        try:
            from src.core.message import sync_messages_to_db

            meta = get_chat_meta(self.shared_folder, self.chat_id)
            chat_type = meta["type"]

            title = "Чат"
            db = LocalDB()

            if chat_type == "dm":
                parts = self.chat_id.replace("dm_", "").split("__")
                if len(parts) == 2:
                    fp1, fp2 = parts
                    other_fp = fp1 if fp2 == self.user_fp16 else fp2
                    title = db.get_login_by_fp16(other_fp)
            elif chat_type == "group":
                title = f"Группа {self.chat_id[4:12]}"
                try:
                    keys = load_chat_keys(self.shared_folder, self.chat_id)
                    wrapped = keys.get("wrapped", {})
                    if self.user_fp16 in wrapped:
                        group_key = unwrap_key(wrapped, self.user_fp16, self.user_priv_pem)
                        enc = load_chat_meta_enc(self.shared_folder, self.chat_id)
                        data = json.loads(enc.decode("utf-8"))
                        if "nonce" in data and "ciphertext" in data:
                            aad = f"chat_id={self.chat_id}|meta".encode("utf-8")
                            decrypted = aes_decrypt(group_key, from_base64(data["nonce"]), from_base64(data["ciphertext"]), aad=aad)
                            meta_group = json.loads(decrypted.decode("utf-8"))
                            title = meta_group.get("name", title)
                except Exception:
                    pass
            elif chat_type == "favorites":
                title = "Избранное"
            elif chat_type == "admin_chat":
                title = "Админ-чат"

            deleted_ids = set(get_deleted_messages(self.shared_folder, self.chat_id, self.user_fp16))

            sync_messages_to_db(
                self.shared_folder, self.chat_id,
                self.user_fp16, self.user_priv_pem
            )

            self.finished.emit({
                "chat_type": chat_type,
                "title": title,
                "deleted_ids": list(deleted_ids)
            })
        except Exception as e:
            logger.error(f"Ошибка фоновой загрузки: {e}")
            self.error.emit(str(e))


class ImageConfirmDialog(QDialog):
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


# ============================================================================
# ОСНОВНОЙ ВИДЖЕТ ЧАТА
# ============================================================================
class ChatViewWidget(QWidget):
    def __init__(self, shared_folder: str | Path, user, parent=None):
        super().__init__(parent)
        self.shared_folder = shared_folder
        self.user = user
        self.current_chat_id = None
        self.current_other_fp = None

        self._rendered_msg_ids: set[str] = set()
        self._rendered_file_count = 0
        self._rendered_read_count = -1
        self._sending = False
        self._load_worker = None
        self._active_workers = []

        self.selection_mode = False
        self.selected_msg_ids = set()

        self.my_msg_bg = "#4a90e2"
        self.other_msg_bg = "#e2a04a"

        self._setup_ui()

        self._apply_chat_background()

        self.emoji_picker = EmojiPicker()
        self.emoji_picker.emoji_selected.connect(self._insert_emoji)

        self.reaction_picker = EmojiPicker()
        self.reaction_picker.emoji_selected.connect(self._apply_reaction)
        self._reaction_msg_id = None

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(1500)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_messages)
        self.refresh_timer.start(700)

        self.typing_timer = QTimer(self)
        self.typing_timer.setSingleShot(True)
        self.typing_timer.timeout.connect(self._stop_typing)

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.header_widget = QWidget()
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(10, 5, 10, 5)
        header_layout.setSpacing(10)

        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(36, 36)
        self.avatar_label.setCursor(Qt.PointingHandCursor)
        self.avatar_label.mousePressEvent = self._on_avatar_clicked
        header_layout.addWidget(self.avatar_label)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(0)

        self.label_title = QLabel("Выберите чат")
        self.label_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        text_layout.addWidget(self.label_title)

        self.label_status = QLabel("")
        self.label_status.setStyleSheet("font-size: 9pt; color: gray;")
        text_layout.addWidget(self.label_status)

        header_layout.addLayout(text_layout)
        header_layout.addStretch()

        layout.addWidget(self.header_widget)

        self.messages_list = ChatMessagesList()
        self.messages_list.setObjectName("messages_list")
        layout.addWidget(self.messages_list)

        # --- ПАНЕЛЬ РЕЖИМА ВЫДЕЛЕНИЯ ---
        self.selection_bar = QWidget()
        self.selection_bar.setStyleSheet("background-color: #313148; border-radius: 8px;")
        self.selection_bar.setFixedHeight(50)
        sel_layout = QHBoxLayout(self.selection_bar)
        sel_layout.setContentsMargins(10, 5, 10, 5)

        self.lbl_selected = QLabel("Выбрано: 0")
        self.lbl_selected.setStyleSheet("font-weight: bold; color: white;")
        sel_layout.addWidget(self.lbl_selected)
        sel_layout.addStretch()

        btn_delete = QPushButton("Удалить выбранные")
        btn_delete.setStyleSheet("background-color: #f38ba8; color: white; font-weight: bold;")
        btn_delete.clicked.connect(self._delete_selected_messages)
        sel_layout.addWidget(btn_delete)

        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self._exit_selection_mode)
        sel_layout.addWidget(btn_cancel)

        layout.addWidget(self.selection_bar)
        self.selection_bar.setVisible(False)

        self.input_widget = QWidget()
        self.input_widget.setFixedHeight(60)

        input_layout = QHBoxLayout(self.input_widget)
        input_layout.setContentsMargins(0, 0, 0, 0)

        db = LocalDB()
        emoji_btn = db.get_setting("emoji_button", "😊")
        self.btn_emoji = QPushButton(emoji_btn)
        self.btn_emoji.setFixedSize(40, 40)
        self.btn_emoji.setCursor(Qt.PointingHandCursor)
        self.btn_emoji.clicked.connect(self._on_emoji_clicked)
        input_layout.addWidget(self.btn_emoji)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Введите сообщение...")
        self.input_field.returnPressed.connect(self._on_send_clicked)
        self.input_field.installEventFilter(self)
        input_layout.addWidget(self.input_field)

        self.btn_attach = QPushButton("📎")
        self.btn_attach.setFixedSize(40, 40)
        self.btn_attach.setCursor(Qt.PointingHandCursor)
        self.btn_attach.clicked.connect(self._on_attach_clicked)
        input_layout.addWidget(self.btn_attach)

        self.btn_send = QPushButton("Отправить")
        self.btn_send.clicked.connect(self._on_send_clicked)
        input_layout.addWidget(self.btn_send)

        layout.addWidget(self.input_widget)
        self.input_widget.setVisible(False)

    def _apply_chat_background(self):
        db = LocalDB()
        bg_image_path = db.get_setting("chat_bg_image", "")

        if bg_image_path and os.path.exists(bg_image_path):
            self.messages_list.set_background_image(bg_image_path)
        else:
            self.messages_list.set_background_image("")

    def eventFilter(self, obj, event):
        if obj is self.input_field and event.type() == QEvent.KeyPress:
            if self.current_chat_id and self.current_other_fp:
                set_typing(self.shared_folder, self.user.fp16, self.current_chat_id, True)
                self.typing_timer.start(3000)

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
                                    self.user.fp16, self.user.priv_pem, temp_path,
                                )
                                self.load_chat(self.current_chat_id)
                            except Exception as e:
                                logger.error(f"Ошибка отправки скриншота: {e}")
                            temp_path.unlink(missing_ok=True)
                        return True
        return super().eventFilter(obj, event)

    def _enter_selection_mode(self):
        self.selection_mode = True
        self.selected_msg_ids.clear()
        self.selection_bar.setVisible(True)
        self.input_widget.setVisible(False)
        self._update_selection_ui()

    def _exit_selection_mode(self):
        self.selection_mode = False
        self.selected_msg_ids.clear()
        self.selection_bar.setVisible(False)
        self.input_widget.setVisible(True)

        for i in range(self.messages_list.count()):
            w = self.messages_list.itemWidget(self.messages_list.item(i))
            if isinstance(w, MessageWidget):
                w.set_selected(False)

    def _update_selection_ui(self):
        self.lbl_selected.setText(f"Выбрано: {len(self.selected_msg_ids)}")

    def _toggle_message_selection(self, msg_id: str):
        if msg_id in self.selected_msg_ids:
            self.selected_msg_ids.remove(msg_id)
        else:
            self.selected_msg_ids.add(msg_id)

        for i in range(self.messages_list.count()):
            item = self.messages_list.item(i)
            w = self.messages_list.itemWidget(item)
            if isinstance(w, MessageWidget) and w.msg_id == msg_id:
                db = LocalDB()
                font_size = int(db.get_setting("font_size", "14"))
                w.set_selected(msg_id in self.selected_msg_ids, font_size)
                break

        self._update_selection_ui()

    def _delete_selected_messages(self):
        if not self.selected_msg_ids:
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Удаление")
        msg_box.setText(f"Удалить {len(self.selected_msg_ids)} сообщений?")
        btn_self = msg_box.addButton("Удалить у себя", QMessageBox.ActionRole)
        btn_all = msg_box.addButton("Удалить у всех", QMessageBox.ActionRole)
        btn_cancel = msg_box.addButton("Отмена", QMessageBox.RejectRole)

        msg_box.exec()

        if msg_box.clickedButton() == btn_cancel:
            return

        for_everyone = (msg_box.clickedButton() == btn_all)

        try:
            for msg_id in self.selected_msg_ids:
                delete_message(
                    self.shared_folder, self.current_chat_id,
                    msg_id, self.user.fp16, for_everyone
                )

            self._exit_selection_mode()
            self.load_chat(self.current_chat_id)

        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось удалить: {e}")

    def _on_emoji_clicked(self):
        pos = self.btn_emoji.mapToGlobal(self.btn_emoji.rect().topLeft())
        pos.setY(pos.y() - 450)
        self.emoji_picker.move(pos)
        self.emoji_picker.show()

    def _insert_emoji(self, emoji: str):
        current_text = self.input_field.text()
        cursor_pos = self.input_field.cursorPosition()
        new_text = current_text[:cursor_pos] + emoji + current_text[cursor_pos:]
        self.input_field.setText(new_text)
        self.input_field.setCursorPosition(cursor_pos + len(emoji))
        self.input_field.setFocus()

    def _apply_reaction(self, emoji: str):
        if not self._reaction_msg_id:
            return
        try:
            reactions = get_reactions(
                self.shared_folder, self.current_chat_id, self._reaction_msg_id
            )
            if reactions.get(self.user.fp16) == emoji:
                set_reaction(
                    self.shared_folder, self.current_chat_id,
                    self._reaction_msg_id, self.user.fp16, None,
                )
            else:
                set_reaction(
                    self.shared_folder, self.current_chat_id,
                    self._reaction_msg_id, self.user.fp16, emoji,
                )
            self.load_chat(self.current_chat_id)
        except Exception as e:
            logger.error(f"Ошибка установки реакции: {e}")
        finally:
            self._reaction_msg_id = None

    def _view_image(self, file_path: str):
        if os.path.exists(file_path):
            os.startfile(file_path)

    def _on_message_clicked(self, msg_id: str):
        if self.selection_mode:
            self._toggle_message_selection(msg_id)
            return

        menu = QMenu(self)
        db = LocalDB()
        quick_emoji = db.get_setting("quick_reaction", "❤️")
        reactions = get_reactions(self.shared_folder, self.current_chat_id, msg_id)
        my_reaction = reactions.get(self.user.fp16)

        is_img = False
        img_path = None
        for i in range(self.messages_list.count()):
            item = self.messages_list.item(i)
            w = self.messages_list.itemWidget(item)
            if isinstance(w, MessageWidget) and w.msg_id == msg_id:
                is_img = w.is_image
                img_path = w.file_path
                break

        if is_img and img_path:
            action_view = menu.addAction("🖼 Просмотреть изображение")
            action_view.triggered.connect(lambda: self._view_image(img_path))

        if my_reaction:
            action_remove = menu.addAction(f"Убрать {my_reaction}")
            action_remove.triggered.connect(lambda: self._remove_reaction(msg_id))
            if my_reaction != quick_emoji:
                action_quick = menu.addAction(f"Поставить {quick_emoji}")
                action_quick.triggered.connect(lambda: self._set_reaction(msg_id, quick_emoji))
        else:
            action_quick = menu.addAction(f"Поставить {quick_emoji}")
            action_quick.triggered.connect(lambda: self._set_reaction(msg_id, quick_emoji))

        menu.addSeparator()
        action_all = menu.addAction("Все реакции...")
        action_all.triggered.connect(lambda: self._open_reaction_picker(msg_id))

        menu.addSeparator()
        action_select = menu.addAction("☑️ Выбрать")
        action_select.triggered.connect(lambda: self._enter_selection_mode_and_select(msg_id))

        menu.exec(self.cursor().pos())

    def _enter_selection_mode_and_select(self, msg_id):
        self._enter_selection_mode()
        self._toggle_message_selection(msg_id)

    def _on_message_double_clicked(self, msg_id: str):
        if self.selection_mode:
            return
        db = LocalDB()
        quick_emoji = db.get_setting("quick_reaction", "❤️")
        reactions = get_reactions(self.shared_folder, self.current_chat_id, msg_id)
        if reactions.get(self.user.fp16) == quick_emoji:
            set_reaction(
                self.shared_folder, self.current_chat_id,
                msg_id, self.user.fp16, None,
            )
        else:
            set_reaction(
                self.shared_folder, self.current_chat_id,
                msg_id, self.user.fp16, quick_emoji,
            )
        self.load_chat(self.current_chat_id)

    def _open_reaction_picker(self, msg_id: str):
        self._reaction_msg_id = msg_id
        pos = self.cursor().pos()
        self.reaction_picker.move(pos)
        self.reaction_picker.show()

    def _set_reaction(self, msg_id: str, emoji: str):
        set_reaction(self.shared_folder, self.current_chat_id, msg_id, self.user.fp16, emoji)
        self.load_chat(self.current_chat_id)

    def _remove_reaction(self, msg_id: str):
        set_reaction(self.shared_folder, self.current_chat_id, msg_id, self.user.fp16, None)
        self.load_chat(self.current_chat_id)

    def _create_message_widget(self, msg, read_by_other, profile_dir, font_size):
        db = LocalDB()
        is_me = (msg.sender_fp16 == self.user.fp16)
        sender_name = "Вы" if is_me else db.get_login_by_fp16(msg.sender_fp16)

        avatar_path = profile_dir / f"{msg.sender_fp16}.png"
        avatar_path_str = str(avatar_path) if avatar_path.exists() else None

        dt = datetime.fromtimestamp(msg.ts / 1000)
        time_str = dt.strftime("%H:%M")

        checkmark = ""
        if is_me:
            checkmark = " ✓✓" if msg.msg_id in read_by_other else " ✓"

        reactions = get_reactions(self.shared_folder, self.current_chat_id, msg.msg_id)
        reactions_html = ""
        if reactions:
            from collections import Counter
            counts = Counter(reactions.values())
            parts = [f"{emoji} {count}" for emoji, count in counts.items()]
            reactions_html = ' '.join(parts)

        is_img = False
        img_path = None
        display_text = msg.text

        if msg.text.startswith("[FILE]") and msg.text.endswith("[/FILE]"):
            inner = msg.text[6:-7]
            if "|" in inner:
                stored_name, display_name = inner.split("|", 1)
            else:
                stored_name = display_name = inner

            file_path = chat_files_dir(self.shared_folder, self.current_chat_id) / stored_name
            ext = stored_name.lower().split('.')[-1]

            if ext in ('png', 'jpg', 'jpeg', 'gif', 'bmp'):
                is_img = True
                img_path = str(file_path)
                file_url = QUrl.fromLocalFile(str(file_path)).toString()
                display_text = f'<a href="{file_url}"><img src="{file_url}" width="200" /></a>'
            else:
                file_url = QUrl.fromLocalFile(str(file_path)).toString()
                display_text = f'<a href="{file_url}" style="color: #89b4fa;">📥 {display_name}</a>'

        my_msg_bg = db.get_setting("color_my_msg", "#4a90e2")
        other_msg_bg = db.get_setting("color_other_msg", "#e2a04a")
        msg_bg = my_msg_bg if is_me else other_msg_bg

        widget = MessageWidget(
            msg_id=msg.msg_id,
            sender_name=sender_name,
            text_html=display_text,
            time_str=time_str + checkmark,
            is_me=is_me,
            avatar_path=avatar_path_str,
            reactions_html=reactions_html,
            font_size=font_size,
            is_image=is_img,
            file_path=img_path,
            bg_color=msg_bg,
        )
        widget.clicked.connect(self._on_message_clicked)
        widget.double_clicked.connect(self._on_message_double_clicked)

        if msg.msg_id in self.selected_msg_ids:
            widget.set_selected(True, font_size)

        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        self.messages_list.addItem(item)
        self.messages_list.setItemWidget(item, widget)

    def load_chat(self, chat_id: str):
        self.current_chat_id = chat_id
        self.messages_list.clear()
        self._rendered_msg_ids.clear()
        self._rendered_file_count = 0

        if self.selection_mode:
            self._exit_selection_mode()

        self.input_widget.setVisible(True)

        db = LocalDB()
        profile_dir = Path(self.shared_folder) / ".profiles"
        font_size = int(db.get_setting("font_size", "14"))

        cached_meta = db.get_chat_cache(chat_id)
        if cached_meta:
            chat_type = cached_meta["type"]
            title = cached_meta["title"]
        else:
            chat_type = "unknown"
            title = "Загрузка..."

        self.current_other_fp = None
        if chat_type == "dm":
            parts = chat_id.replace("dm_", "").split("__")
            if len(parts) == 2:
                fp1, fp2 = parts
                self.current_other_fp = fp1 if fp2 == self.user.fp16 else fp2
                avatar_path = profile_dir / f"{self.current_other_fp}.png"
                if avatar_path.exists():
                    pixmap = QPixmap(str(avatar_path))
                    self.avatar_label.setPixmap(pixmap.scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    self.avatar_label.setVisible(True)
        elif chat_type == "group":
            group_avatar_path = profile_dir / f"{chat_id}.png"
            if group_avatar_path.exists():
                pixmap = QPixmap(str(group_avatar_path))
                self.avatar_label.setPixmap(pixmap.scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.avatar_label.setVisible(True)

        self.label_title.setText(title)
        self._update_status()

        cached_msgs = db.get_messages(chat_id)
        cached_msgs = cached_msgs[-100:]

        if cached_msgs:
            read_by_other = []
            if self.current_other_fp:
                read_by_other = get_read_messages(self.shared_folder, chat_id, self.current_other_fp)

            for m in cached_msgs:
                msg_obj = Message(chat_id, m["sender_fp16"], m["text"], m["ts"], m["msg_id"])
                self._create_message_widget(msg_obj, read_by_other, profile_dir, font_size)
                self._rendered_msg_ids.add(m["msg_id"])
            self.messages_list.scrollToBottom()
        else:
            item = QListWidgetItem("Загрузка сообщений...")
            item.setFlags(Qt.NoItemFlags)
            self.messages_list.addItem(item)

        if self._load_worker and self._load_worker.isRunning():
            self._load_worker.terminate()

        self._load_worker = ChatLoadWorker(
            self.shared_folder, chat_id, self.user.fp16, self.user.priv_pem, self.user.login
        )

        def on_loaded(result: dict):
            db.save_chat_cache(chat_id, result["chat_type"], result["title"])
            self.label_title.setText(result["title"])

            if result["chat_type"] == "dm":
                parts = chat_id.replace("dm_", "").split("__")
                if len(parts) == 2:
                    fp1, fp2 = parts
                    self.current_other_fp = fp1 if fp2 == self.user.fp16 else fp2
                    avatar_path = profile_dir / f"{self.current_other_fp}.png"
                    if avatar_path.exists():
                        pixmap = QPixmap(str(avatar_path))
                        self.avatar_label.setPixmap(pixmap.scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                        self.avatar_label.setVisible(True)
                        self.avatar_label.setCursor(Qt.PointingHandCursor)
            elif result["chat_type"] == "group":
                group_avatar_path = profile_dir / f"{chat_id}.png"
                if group_avatar_path.exists():
                    pixmap = QPixmap(str(group_avatar_path))
                    self.avatar_label.setPixmap(pixmap.scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    self.avatar_label.setVisible(True)
                    self.avatar_label.setCursor(Qt.PointingHandCursor)

            self._rendered_file_count = 0
            self._refresh_messages()
            self._update_status()

            if self._load_worker in self._active_workers:
                self._active_workers.remove(self._load_worker)

        self._load_worker.finished.connect(on_loaded)
        self._active_workers.append(self._load_worker)
        self._load_worker.start()

    def _refresh_messages(self):
        if not self.current_chat_id:
            return

        msg_dir = chat_message_dir(self.shared_folder, self.current_chat_id)
        if not msg_dir.is_dir():
            return

        current_count = len(list(msg_dir.glob("*.bin")))
        if current_count <= self._rendered_file_count:
            self._refresh_read_marks()
            return

        try:
            worker = ChatLoadWorker(
                self.shared_folder, self.current_chat_id, self.user.fp16, self.user.priv_pem, self.user.login
            )

            def on_loaded(result: dict):
                db = LocalDB()
                cached_msgs = db.get_messages(self.current_chat_id)

                new_msgs = [
                    Message(self.current_chat_id, m["sender_fp16"], m["text"], m["ts"], m["msg_id"])
                    for m in cached_msgs
                    if m["msg_id"] not in self._rendered_msg_ids
                ]

                if new_msgs:
                    new_msgs.sort(key=lambda m: m.ts)
                    deleted_ids = set(result.get("deleted_ids", []))

                    profile_dir = Path(self.shared_folder) / ".profiles"
                    font_size = int(db.get_setting("font_size", "14"))

                    incoming_ids = [m.msg_id for m in new_msgs if m.sender_fp16 != self.user.fp16]
                    if incoming_ids:
                        mark_messages_read(self.shared_folder, self.current_chat_id, self.user.fp16, incoming_ids)

                    read_by_other = []
                    if self.current_other_fp:
                        read_by_other = get_read_messages(self.shared_folder, self.current_chat_id, self.current_other_fp)

                    for msg in new_msgs:
                        if msg.msg_id in deleted_ids:
                            self._rendered_msg_ids.add(msg.msg_id)
                            continue
                        self._create_message_widget(msg, read_by_other, profile_dir, font_size)
                        self._rendered_msg_ids.add(msg.msg_id)

                    self.messages_list.scrollToBottom()

                self._rendered_file_count = current_count
                self._refresh_read_marks()
                if worker in self._active_workers:
                    self._active_workers.remove(worker)

            worker.finished.connect(on_loaded)
            self._active_workers.append(worker)
            worker.start()

        except Exception as e:
            logger.error(f"Ошибка инкрементального обновления: {e}")

    def _refresh_read_marks(self):
        if not self.current_other_fp:
            return
        read_by_other = get_read_messages(
            self.shared_folder, self.current_chat_id, self.current_other_fp,
        )
        if len(read_by_other) == self._rendered_read_count:
            return
        self._rendered_read_count = len(read_by_other)

    def _update_status(self):
        if not self.current_chat_id or not self.current_other_fp:
            self.label_status.setText("")
            return

        viewer_is_admin = can_read_all_chats(self.shared_folder, self.user.fp16)
        status = get_status(
            self.shared_folder, self.current_other_fp,
            viewer_fp16=self.user.fp16,
            viewer_is_admin=viewer_is_admin,
        )
        typing = (
            status.get("typing", False)
            and status.get("typing_chat") == self.current_chat_id
        )
        online = status.get("online", False)
        last_seen = status.get("last_seen", 0)

        if typing:
            self.label_status.setText("печатает...")
        elif online:
            self.label_status.setText("в сети")
        elif status.get("_hidden"):
            self.label_status.setText("был(а) недавно")
        elif last_seen > 0:
            dt = datetime.fromtimestamp(last_seen)
            self.label_status.setText(f"был(а) в сети {dt.strftime('%d.%m %H:%M')}")
        else:
            self.label_status.setText("не в сети")

    def _stop_typing(self):
        if self.current_chat_id:
            set_typing(self.shared_folder, self.user.fp16, self.current_chat_id, False)

    def _on_avatar_clicked(self, event):
        if not self.current_chat_id:
            return
        meta = get_chat_meta(self.shared_folder, self.current_chat_id)
        if meta["type"] == "dm" and self.current_other_fp:
            from src.ui.profile_view import ProfileView
            self.profile_window = ProfileView(
                self.shared_folder, self.user, target_fp16=self.current_other_fp,
            )
            self.profile_window.show()
        elif meta["type"] == "group":
            from src.ui.group_settings_view import GroupSettingsView
            self.group_window = GroupSettingsView(
                self.shared_folder, self.user, self.current_chat_id,
            )
            self.group_window.show()

    def _on_attach_clicked(self):
        if not self.current_chat_id:
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите файл")
        if file_path:
            try:
                send_file(
                    self.shared_folder, self.current_chat_id,
                    self.user.fp16, self.user.priv_pem, file_path,
                )
                self.load_chat(self.current_chat_id)
            except Exception as e:
                logger.error(f"Ошибка отправки файла: {e}")

    def _on_send_clicked(self):
        if not self.current_chat_id or self._sending:
            return

        text = self.input_field.text().strip()
        if not text:
            return

        self.input_field.clear()
        self._sending = True

        temp_ts = int(time.time() * 1000)
        temp_msg_id = f"pending_{temp_ts}_{self.user.fp16}"

        temp_msg = Message(
            chat_id=self.current_chat_id,
            sender_fp16=self.user.fp16,
            text=text,
            ts=temp_ts,
            msg_id=temp_msg_id,
        )

        db = LocalDB()
        profile_dir = Path(self.shared_folder) / ".profiles"
        font_size = int(db.get_setting("font_size", "14"))

        self._create_message_widget(temp_msg, [], profile_dir, font_size)
        self._rendered_msg_ids.add(temp_msg_id)
        self.messages_list.scrollToBottom()

        worker = SendWorker(
            self.shared_folder,
            self.current_chat_id,
            self.user.fp16,
            self.user.priv_pem,
            text,
        )

        def on_finished(success, error_msg, real_msg_id):
            self._sending = False
            if success:
                self._rendered_msg_ids.discard(temp_msg_id)
                self._rendered_msg_ids.add(real_msg_id)
            else:
                logger.error(f"Не удалось отправить сообщение: {error_msg}")
                self.load_chat(self.current_chat_id)
            if worker in self._active_workers:
                self._active_workers.remove(worker)

        worker.finished.connect(on_finished)
        self._active_workers.append(worker)
        worker.start()