"""Виджет окна чата Pygram (ускоренный + конфиденциальность)."""

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
from PySide6.QtGui import QDesktopServices, QKeySequence, QPixmap, QGuiApplication
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


class SendWorker(QThread):
    """Фоновый поток для шифрования и отправки сообщений."""

    finished = Signal(bool, str, str)  # (успех, error, msg_id)

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
            logger.error(f"Ошибка отправки сообщения в фоне: {e}")
            self.finished.emit(False, str(e), "")


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


class ChatViewWidget(QWidget):
    def __init__(self, shared_folder: str | Path, user, parent=None):
        super().__init__(parent)
        self.shared_folder = shared_folder
        self.user = user
        self.current_chat_id = None
        self.current_other_fp = None

        self._is_loading = False
        self._rendered_msg_ids: set[str] = set()
        self._rendered_file_count = 0
        self._rendered_read_count = -1
        self._rendered_deleted_count = -1
        self._sending = False

        self._active_workers = []

        self._setup_ui()

        self.emoji_picker = EmojiPicker()
        self.emoji_picker.emoji_selected.connect(self._insert_emoji)

        self.reaction_picker = EmojiPicker()
        self.reaction_picker.emoji_selected.connect(self._apply_reaction)
        self._reaction_msg_id = None

        # Быстрый статус (было 2000 — стало 1500)
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(1500)

        # Быстрое обновление сообщений (было 2000 — стало 700)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_messages)
        self.refresh_timer.start(700)

        self.typing_timer = QTimer(self)
        self.typing_timer.setSingleShot(True)
        self.typing_timer.timeout.connect(self._stop_typing)

    # ========================================================================
    # UI
    # ========================================================================

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

        self.messages_list = QListWidget()
        self.messages_list.setObjectName("messages_list")
        self.messages_list.setStyleSheet("""
            QListWidget { background-color: transparent; border: none; outline: none; }
            QListWidget::item { padding: 0px; margin: 0px; }
            QListWidget::item:selected { background: transparent; }
        """)
        self.messages_list.setSelectionMode(QListWidget.NoSelection)
        layout.addWidget(self.messages_list)

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

    # ========================================================================
    # События ввода
    # ========================================================================

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

    # ========================================================================
    # Эмодзи / реакции
    # ========================================================================

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

    # ========================================================================
    # Меню сообщения
    # ========================================================================

    def _on_message_clicked(self, msg_id: str):
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
        action_delete = menu.addAction("🗑 Удалить сообщение")
        action_delete.triggered.connect(lambda: self._show_delete_menu(msg_id))
        menu.exec(self.cursor().pos())

    def _show_delete_menu(self, msg_id: str):
        menu = QMenu(self)
        action_self = menu.addAction("Удалить у себя")
        action_self.triggered.connect(lambda: self._delete_message(msg_id, for_everyone=False))
        action_all = menu.addAction("Удалить у обоих")
        action_all.triggered.connect(lambda: self._delete_message(msg_id, for_everyone=True))
        menu.exec(self.cursor().pos())

    def _delete_message(self, msg_id: str, for_everyone: bool):
        try:
            delete_message(
                self.shared_folder, self.current_chat_id, msg_id,
                self.user.fp16, for_everyone,
            )
            self.load_chat(self.current_chat_id)
        except Exception as e:
            logger.error(f"Ошибка удаления: {e}")

    def _on_message_double_clicked(self, msg_id: str):
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

    # ========================================================================
    # Рендер сообщения
    # ========================================================================

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
        )
        widget.clicked.connect(self._on_message_clicked)
        widget.double_clicked.connect(self._on_message_double_clicked)

        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        self.messages_list.addItem(item)
        self.messages_list.setItemWidget(item, widget)

    # ========================================================================
    # Загрузка чата
    # ========================================================================

    def load_chat(self, chat_id: str):
        if self._is_loading:
            return
        self._is_loading = True
        try:
            self.current_chat_id = chat_id
            self.messages_list.clear()
            self._rendered_msg_ids.clear()
            self._rendered_file_count = 0
            self._rendered_read_count = -1
            self._rendered_deleted_count = -1

            self.avatar_label.setVisible(False)
            self.avatar_label.clear()
            self.avatar_label.setStyleSheet("")
            self.avatar_label.setCursor(Qt.ArrowCursor)
            self.label_status.setText("")
            self.input_widget.setVisible(True)

            try:
                meta = get_chat_meta(self.shared_folder, chat_id)
                chat_type = meta["type"]
                db = LocalDB()
                profile_dir = Path(self.shared_folder) / ".profiles"
                font_size = int(db.get_setting("font_size", "14"))

                self.current_other_fp = None
                if chat_type == "dm":
                    parts = chat_id.replace("dm_", "").split("__")
                    if len(parts) == 2:
                        fp1, fp2 = parts
                        self.current_other_fp = fp1 if fp2 == self.user.fp16 else fp2
                        title = db.get_login_by_fp16(self.current_other_fp)
                        avatar_path = profile_dir / f"{self.current_other_fp}.png"
                        if avatar_path.exists():
                            pixmap = QPixmap(str(avatar_path))
                            self.avatar_label.setPixmap(
                                pixmap.scaled(36, 36, Qt.KeepAspectRatio,
                                              Qt.SmoothTransformation)
                            )
                            self.avatar_label.setVisible(True)
                            self.avatar_label.setCursor(Qt.PointingHandCursor)
                    else:
                        title = "Личный чат"
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
                                decrypted = aes_decrypt(
                                    group_key,
                                    from_base64(data["nonce"]),
                                    from_base64(data["ciphertext"]),
                                    aad=aad,
                                )
                                meta_group = json.loads(decrypted.decode("utf-8"))
                                group_name = meta_group.get("name", group_name)
                    except Exception as e:
                        logger.error(f"Не удалось расшифровать имя группы: {e}")
                    title = group_name
                    group_avatar_path = profile_dir / f"{chat_id}.png"
                    if group_avatar_path.exists():
                        pixmap = QPixmap(str(group_avatar_path))
                        self.avatar_label.setPixmap(
                            pixmap.scaled(36, 36, Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation)
                        )
                        self.avatar_label.setVisible(True)
                        self.avatar_label.setCursor(Qt.PointingHandCursor)
                elif chat_type == "favorites":
                    title = "Избранное"
                elif chat_type == "admin_chat":
                    title = "Админ-чат"
                else:
                    title = chat_id

                self.label_title.setText(title)
                self._update_status()

                messages = read_messages(
                    self.shared_folder, chat_id, self.user.fp16, self.user.priv_pem,
                )
                deleted_ids = get_deleted_messages(
                    self.shared_folder, chat_id, self.user.fp16,
                )
                messages = [m for m in messages if m.msg_id not in deleted_ids]

                if not messages:
                    item = QListWidgetItem("Нет сообщений. Напишите первым!")
                    item.setFlags(Qt.NoItemFlags)
                    self.messages_list.addItem(item)
                    return

                incoming_ids = [m.msg_id for m in messages if m.sender_fp16 != self.user.fp16]
                if incoming_ids:
                    mark_messages_read(
                        self.shared_folder, chat_id, self.user.fp16, incoming_ids,
                    )

                read_by_other: list[str] = []
                if self.current_other_fp:
                    read_by_other = get_read_messages(
                        self.shared_folder, chat_id, self.current_other_fp,
                    )

                for msg in messages:
                    self._create_message_widget(msg, read_by_other, profile_dir, font_size)
                    self._rendered_msg_ids.add(msg.msg_id)

                msg_dir = chat_message_dir(self.shared_folder, chat_id)
                if msg_dir.is_dir():
                    self._rendered_file_count = len(list(msg_dir.glob("*.bin")))
                self._rendered_read_count = len(read_by_other)
                self._rendered_deleted_count = len(deleted_ids)
                self.messages_list.scrollToBottom()

            except Exception as e:
                logger.error(f"Ошибка загрузки чата {chat_id}: {e}")
                item = QListWidgetItem(f"Ошибка: {e}")
                item.setFlags(Qt.NoItemFlags)
                self.messages_list.addItem(item)
        finally:
            self._is_loading = False

    # ========================================================================
    # Инкрементальное обновление
    # ========================================================================

    def _refresh_messages(self):
        if not self.current_chat_id or self._is_loading:
            return

        msg_dir = chat_message_dir(self.shared_folder, self.current_chat_id)
        if not msg_dir.is_dir():
            return

        current_count = len(list(msg_dir.glob("*.bin")))
        if current_count <= self._rendered_file_count:
            # Только галочки могли измениться
            self._refresh_read_marks()
            return

        try:
            new_msgs = read_new_messages(
                self.shared_folder, self.current_chat_id,
                self.user.fp16, self.user.priv_pem, self._rendered_msg_ids,
            )
            if not new_msgs:
                self._rendered_file_count = current_count
                return

            # Учитываем удалённые (могли пометить между опросами)
            deleted_ids = set(get_deleted_messages(
                self.shared_folder, self.current_chat_id, self.user.fp16,
            ))

            db = LocalDB()
            profile_dir = Path(self.shared_folder) / ".profiles"
            font_size = int(db.get_setting("font_size", "14"))

            incoming_ids = [
                m.msg_id for m in new_msgs
                if m.sender_fp16 != self.user.fp16 and m.msg_id not in deleted_ids
            ]
            if incoming_ids:
                mark_messages_read(
                    self.shared_folder, self.current_chat_id,
                    self.user.fp16, incoming_ids,
                )

            read_by_other: list[str] = []
            if self.current_other_fp:
                read_by_other = get_read_messages(
                    self.shared_folder, self.current_chat_id, self.current_other_fp,
                )

            for msg in new_msgs:
                if msg.msg_id in deleted_ids:
                    self._rendered_msg_ids.add(msg.msg_id)
                    continue
                self._create_message_widget(msg, read_by_other, profile_dir, font_size)
                self._rendered_msg_ids.add(msg.msg_id)

            self.messages_list.scrollToBottom()
            self._rendered_file_count = current_count
            self._refresh_read_marks()
        except Exception as e:
            logger.error(f"Ошибка инкрементального обновления: {e}")

    def _refresh_read_marks(self):
        """Обновляет галочки, не перерисовывая список целиком.

        Простая реализация: если количество изменилось — перерисовываем
        только «мои» виджеты (пересоздаём их text/время). Для простоты
        сейчас — no-op, т.к. следующий _refresh_messages перерисует при
        новых сообщениях. При желании — можно хранить ссылки на виджеты.
        """
        if not self.current_other_fp:
            return
        read_by_other = get_read_messages(
            self.shared_folder, self.current_chat_id, self.current_other_fp,
        )
        if len(read_by_other) == self._rendered_read_count:
            return
        self._rendered_read_count = len(read_by_other)
        # Для мгновенного визуального отклика — перерисуем текущий чат
        # (не идеально, но надёжно; можно оптимизировать позже)
        # Оставляем как есть — следующий новый месседж обновит и галочки.

    # ========================================================================
    # Статус (с конфиденциальностью)
    # ========================================================================

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

    # ========================================================================
    # Аватар / вложения
    # ========================================================================

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

    # ========================================================================
    # Отправка (с защитой от дублей)
    # ========================================================================

    def _on_send_clicked(self):
        if not self.current_chat_id:
            return
        if self._sending:
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
                self.load_chat(self.current_chat_id)  # откат
            if worker in self._active_workers:
                self._active_workers.remove(worker)

        worker.finished.connect(on_finished)
        self._active_workers.append(worker)
        worker.start()