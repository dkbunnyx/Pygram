"""Виджет окна чата Pygram (Максимальная оптимизация)."""

from pathlib import Path
import json
import os
import shutil
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QDialog,
    QListView, QListWidget, QListWidgetItem, QLineEdit, QPushButton,
    QLabel, QFileDialog, QMessageBox, QMenu, QAbstractItemView,
    QProgressBar
)
from PySide6.QtCore import Qt, QEvent, QTimer, QThread, Signal, QAbstractListModel, QModelIndex, QPoint
from PySide6.QtGui import QKeySequence, QPixmap, QGuiApplication, QPainter
from loguru import logger
import tempfile
import time

from src.core.message import (
    send_message, send_file, sync_messages_to_db
)
from src.core.chat_logic import get_chat_meta, delete_group_chat, get_group_display_name
from src.core.crypto import unwrap_key, aes_decrypt, from_base64
from src.core.admin import can_read_all_chats
from src.storage.local_db import LocalDB
from src.storage.shared_store import (
    chat_files_dir, chat_message_dir, load_chat_keys, load_chat_meta_enc,
)
from src.core.status import (
    get_status, set_typing, mark_messages_read, get_read_messages,
    set_reaction, get_reactions, delete_message, get_deleted_messages, DIR_STATUS
)
from src.ui.widgets.emoji_picker import EmojiPicker
from src.ui.widgets.message_delegate import MessageDelegate
from src.transport.file_transport import FileTransport


class ResizableListView(QListView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bg_pixmap = None

    def set_background_image(self, image_path: str):
        if image_path and os.path.exists(image_path):
            self.bg_pixmap = QPixmap(image_path)
        else:
            self.bg_pixmap = None
        self.viewport().update()

    def paintEvent(self, event):
        if self.bg_pixmap:
            painter = QPainter(self.viewport())
            scaled = self.bg_pixmap.scaled(
                self.viewport().size(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation
            )
            x = (self.viewport().width() - scaled.width()) // 2
            y = (self.viewport().height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            painter.end()

        super().paintEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(10, self.viewport().update)


class MessagesModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self.messages = []

    def rowCount(self, parent=QModelIndex()):
        return len(self.messages)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.UserRole:
            return self.messages[index.row()]
        return None

    def add_messages(self, msgs):
        if not msgs:
            return
        start = len(self.messages)
        self.beginInsertRows(QModelIndex(), start, start + len(msgs) - 1)
        self.messages.extend(msgs)
        self.endInsertRows()

    def prepend_messages(self, msgs):
        if not msgs:
            return
        self.beginInsertRows(QModelIndex(), 0, len(msgs) - 1)
        self.messages = msgs + self.messages
        self.endInsertRows()

    def clear(self):
        self.beginResetModel()
        self.messages = []
        self.endResetModel()

    def remove_message_by_id(self, msg_id: str):
        for i, m in enumerate(self.messages):
            if m["msg_id"] == msg_id:
                self.beginRemoveRows(QModelIndex(), i, i)
                self.messages.pop(i)
                self.endRemoveRows()
                return True
        return False

    def update_message_reactions(self, msg_id: str, reactions: dict):
        for i, m in enumerate(self.messages):
            if m["msg_id"] == msg_id:
                m["reactions"] = reactions
                idx = self.index(i)
                self.dataChanged.emit(idx, idx, [Qt.UserRole])
                return True
        return False


class SyncWorker(QThread):
    finished = Signal()

    def __init__(self, shared_folder, chat_id, user_fp16, user_priv_pem):
        super().__init__()
        self.shared_folder = shared_folder
        self.chat_id = chat_id
        self.user_fp16 = user_fp16
        self.user_priv_pem = user_priv_pem

    def run(self):
        try:
            sync_messages_to_db(self.shared_folder, self.chat_id, self.user_fp16, self.user_priv_pem)
            self.finished.emit()
        except Exception as e:
            logger.error(f"Ошибка синхронизации: {e}")


class SendWorker(QThread):
    finished = Signal(bool, str)

    def __init__(self, shared_folder, chat_id, user_fp16, user_priv_pem, text, db):
        super().__init__()
        self.shared_folder = shared_folder
        self.chat_id = chat_id
        self.user_fp16 = user_fp16
        self.user_priv_pem = user_priv_pem
        self.text = text
        self.db = db

    def run(self):
        try:
            real_id = send_message(self.shared_folder, self.chat_id, self.user_fp16, self.user_priv_pem, self.text)
            self.db.save_message(real_id, self.chat_id, self.user_fp16, self.text, int(time.time() * 1000))
            self.finished.emit(True, real_id)
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")
            self.finished.emit(False, str(e))


class DeleteWorker(QThread):
    finished = Signal()

    def __init__(self, shared_folder, chat_id, msg_ids, user_fp16, for_everyone, db):
        super().__init__()
        self.shared_folder = shared_folder
        self.chat_id = chat_id
        self.msg_ids = msg_ids
        self.user_fp16 = user_fp16
        self.for_everyone = for_everyone
        self.db = db

    def run(self):
        try:
            for msg_id in self.msg_ids:
                if not msg_id.startswith("pending_"):
                    delete_message(self.shared_folder, self.chat_id, msg_id, self.user_fp16, self.for_everyone)
            self.finished.emit()
        except Exception as e:
            logger.error(f"Ошибка фонового удаления: {e}")


class DownloadWorker(QThread):
    """Поток для скачивания файла с обновлением прогресса."""
    progress = Signal(int, int, int)  # (процент, скачано_байт, всего_байт)
    finished = Signal(bool, str)

    def __init__(self, src_path: Path, dest_path: Path):
        super().__init__()
        self.src_path = src_path
        self.dest_path = dest_path

    def run(self):
        try:
            total_size = self.src_path.stat().st_size
            copied = 0
            chunk_size = 1024 * 1024  # 1 МБ

            with open(self.src_path, "rb") as fsrc, open(self.dest_path, "wb") as fdst:
                while True:
                    chunk = fsrc.read(chunk_size)
                    if not chunk:
                        break
                    fdst.write(chunk)
                    copied += len(chunk)
                    percent = int((copied / total_size) * 100)
                    self.progress.emit(percent, copied, total_size)

            self.finished.emit(True, "")
        except Exception as e:
            logger.error(f"Ошибка скачивания: {e}")
            if self.dest_path.exists():
                self.dest_path.unlink(missing_ok=True)
            self.finished.emit(False, str(e))


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


class DownloadProgressDialog(QDialog):
    def __init__(self, filename: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Скачивание файла")
        self.resize(450, 120)
        self.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        self.setWindowModality(Qt.ApplicationModal)

        layout = QVBoxLayout(self)
        self.label = QLabel(f"Скачивание: {filename}")
        self.label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.label_details = QLabel("0.00 МБ / 0.00 МБ")
        self.label_details.setAlignment(Qt.AlignRight)
        self.label_details.setStyleSheet("color: gray; font-size: 10pt;")
        layout.addWidget(self.label_details)

    def update_progress(self, percent: int, copied: int, total: int):
        self.progress_bar.setValue(percent)
        mb_copied = copied / (1024 * 1024)
        mb_total = total / (1024 * 1024)
        self.label_details.setText(f"{mb_copied:.2f} МБ / {mb_total:.2f} МБ")


class ChatViewWidget(QWidget):
    def __init__(self, shared_folder: str | Path, user, parent=None):
        super().__init__(parent)
        self.shared_folder = shared_folder
        self.user = user
        self.db = LocalDB()

        self.current_chat_id = None
        self.current_other_fp = None

        self._sync_worker = None
        self._active_workers = []

        self.loaded_offset = 0
        self.limit = 50

        self._last_deleted_count = -1
        self._last_file_count = -1
        self._last_reactions_hash = -1
        self._last_read_hash = -1

        # П.9: кэш реакций по msg_id
        self._reactions_cache: dict[str, dict] = {}

        self.selection_mode = False
        self.selected_msg_ids = set()

        self._setup_ui()
        self._apply_chat_background()

        self.emoji_picker = EmojiPicker()
        self.emoji_picker.emoji_selected.connect(self._insert_emoji)

        self.reaction_picker = EmojiPicker()
        self.reaction_picker.emoji_selected.connect(self._apply_reaction)
        self._reaction_msg_id = None

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(1000)

        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self._sync_and_render)
        self.sync_timer.start(500)

        self.typing_timer = QTimer(self)
        self.typing_timer.setSingleShot(True)
        self.typing_timer.timeout.connect(self._stop_typing)

        self.transport = FileTransport(shared_folder)
        # П.4: watchdog запускается в load_chat() на папку конкретного чата.
        # Watch на всю шару ('.') не используем — дорого и шумно.

    def _on_file_changed(self, path: str):
        if self.current_chat_id and self.current_chat_id in path:
            QTimer.singleShot(0, self._trigger_sync)

    def _rewatch_current_chat(self) -> None:
        """Перезапускает watchdog на папку сообщений текущего чата."""
        try:
            self.transport.stop_watch()
        except Exception as e:
            logger.debug(f"stop_watch: {e}")

        if not self.current_chat_id:
            return

        rel_dir = f"message/{self.current_chat_id}"
        try:
            self.transport.watch(rel_dir, self._on_file_changed)
        except Exception as e:
            logger.error(f"Не удалось запустить watchdog на {rel_dir}: {e}")

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
        self.label_title.setCursor(Qt.PointingHandCursor)
        self.label_title.mousePressEvent = self._on_title_clicked
        text_layout.addWidget(self.label_title)

        self.label_status = QLabel("")
        self.label_status.setStyleSheet("font-size: 9pt; color: gray;")
        text_layout.addWidget(self.label_status)
        header_layout.addLayout(text_layout)

        header_layout.addStretch()

        self.btn_chat_menu = QPushButton("⋮")
        self.btn_chat_menu.setFixedSize(30, 30)
        self.btn_chat_menu.setStyleSheet("font-size: 20px; font-weight: bold; background: transparent; border: none;")
        self.btn_chat_menu.setCursor(Qt.PointingHandCursor)
        self.btn_chat_menu.clicked.connect(self._on_chat_menu_clicked)
        header_layout.addWidget(self.btn_chat_menu)

        layout.addWidget(self.header_widget)

        self.messages_model = MessagesModel()
        self.messages_view = ResizableListView()
        self.messages_view.setModel(self.messages_model)
        self.messages_view.setStyleSheet("background-color: transparent; border: none;")
        self.messages_view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.messages_view.setSelectionMode(QAbstractItemView.NoSelection)
        self.messages_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.messages_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.messages_view.customContextMenuRequested.connect(self._on_message_context_menu)

        self.messages_view.clicked.connect(self._on_message_left_click)

        self.delegate = MessageDelegate()
        self.messages_view.setItemDelegate(self.delegate)

        self.messages_view.verticalScrollBar().valueChanged.connect(self._on_scroll)

        layout.addWidget(self.messages_view)

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

        emoji_btn = self.db.get_setting("emoji_button", "😊")
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
        bg_image_path = self.db.get_setting("chat_bg_image", "")
        if bg_image_path and os.path.exists(bg_image_path):
            self.messages_view.setStyleSheet("background-color: transparent; border: none;")
            self.messages_view.set_background_image(bg_image_path)
        else:
            self.messages_view.set_background_image("")
            self.messages_view.setStyleSheet("background-color: transparent; border: none;")

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
                                send_file(self.shared_folder, self.current_chat_id, self.user.fp16, self.user.priv_pem, temp_path)
                                self._trigger_sync()
                            except Exception as e:
                                logger.error(f"Ошибка отправки скриншота: {e}")
                            temp_path.unlink(missing_ok=True)
                        return True
        return super().eventFilter(obj, event)

    def load_chat(self, chat_id: str):
        self.current_chat_id = chat_id
        self.messages_model.clear()
        self.loaded_offset = 0

        self._last_deleted_count = -1
        self._last_file_count = -1
        self._last_reactions_hash = -1
        self._last_read_hash = -1
        self._reactions_cache.clear()

        self._rewatch_current_chat()

        if self.selection_mode:
            self._exit_selection_mode()

        self.input_widget.setVisible(True)

        profile_dir = Path(self.shared_folder) / ".profiles"
        font_size = int(self.db.get_setting("font_size", "14"))

        cached_meta = self.db.get_chat_cache(chat_id)
        if cached_meta:
            chat_type = cached_meta["type"]
            title = cached_meta["title"]
        else:
            chat_type = "unknown"
            title = "Чат"
            if chat_id.startswith("dm_"):
                chat_type = "dm"
                parts = chat_id.replace("dm_", "").split("__")
                if len(parts) == 2:
                    fp1, fp2 = parts
                    other_fp = fp1 if fp2 == self.user.fp16 else fp2
                    title = self.db.get_login_by_fp16(other_fp)
            elif chat_id.startswith("grp_"):
                chat_type = "group"
                title = f"Группа {chat_id[4:12]}"
            elif chat_id.startswith("fav_"):
                title = "Избранное"
            elif chat_id == "admin_chat":
                title = "Админ-чат"

        if chat_type == "group" and title.startswith("Группа "):
            real_name = get_group_display_name(
                self.shared_folder, chat_id, self.user.fp16, self.user.priv_pem,
            )
            if real_name:
                title = real_name
                self.db.save_chat_cache(chat_id, "group", title)

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
                else:
                    self.avatar_label.setVisible(False)
        elif chat_type == "group":
            group_avatar_path = profile_dir / f"{chat_id}.png"
            if group_avatar_path.exists():
                pixmap = QPixmap(str(group_avatar_path))
                self.avatar_label.setPixmap(pixmap.scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.avatar_label.setVisible(True)
            else:
                self.avatar_label.setVisible(False)
        else:
            self.avatar_label.setVisible(False)

        self.label_title.setText(title)
        self._update_status()

        self.delegate.font_size = font_size
        self.delegate.show_header = (chat_type != "dm")
        self.delegate.profile_dir = profile_dir
        self.delegate.db = self.db
        self.delegate.my_msg_bg = self.db.get_setting("color_my_msg", "#4a90e2")
        self.delegate.other_msg_bg = self.db.get_setting("color_other_msg", "#e2a04a")
        self.delegate.chat_files_dir = chat_files_dir(self.shared_folder, chat_id)

        self.messages_view.setItemDelegate(self.delegate)
        self.messages_view.scrollToBottom()

        self._load_page()
        self._trigger_sync()

    def _on_scroll(self, value):
        if value == 0 and self.loaded_offset > 0:
            self._load_page()

    def _load_page(self):
        if not self.current_chat_id:
            return

        msgs = self.db.get_messages_paginated(self.current_chat_id, self.limit, self.loaded_offset)

        if msgs:
            deleted_ids = set(get_deleted_messages(self.shared_folder, self.current_chat_id, self.user.fp16))

            formatted_msgs = []
            incoming_to_mark = []

            for m in msgs:
                if m["msg_id"] in deleted_ids:
                    continue
                formatted_msgs.append({
                    "msg_id": m["msg_id"],
                    "sender_fp16": m["sender_fp16"],
                    "text": m["text"],
                    "ts": m["ts"],
                    "is_me": (m["sender_fp16"] == self.user.fp16),
                    "read_status": "",  # Пусто, _refresh_read_status обновит при необходимости
                    "reactions": self._get_reactions_cached(m["msg_id"]),
                })

                if m["sender_fp16"] != self.user.fp16:
                    incoming_to_mark.append(m["msg_id"])

            self.messages_model.prepend_messages(formatted_msgs)
            self.loaded_offset += self.limit

            if incoming_to_mark:
                # Локальная БД (для счётчика и UI)
                self.db.mark_messages_read(self.current_chat_id, incoming_to_mark)
                # Шара (для галочек у отправителя)
                mark_messages_read(
                    self.shared_folder, self.current_chat_id,
                    self.user.fp16, incoming_to_mark,
                )

    def _get_reactions_cached(self, msg_id: str) -> dict:
        """Реакции из кэша; при отсутствии — читает и кладёт в кэш."""
        if msg_id not in self._reactions_cache:
            self._reactions_cache[msg_id] = get_reactions(
                self.shared_folder, self.current_chat_id, msg_id
            )
        return self._reactions_cache[msg_id]

    def _refresh_reactions_if_changed(self) -> None:
        """Считает хеш папки реакций текущего чата; если изменился —
        обновляет кэш и перерисовывает только затронутые сообщения."""
        reactions_dir = Path(self.shared_folder) / DIR_STATUS / "reactions"
        if not reactions_dir.is_dir():
            return

        h = 0
        try:
            for f in reactions_dir.glob(f"{self.current_chat_id}_*.json"):
                try:
                    st = f.stat()
                    h = hash((h, f.name, st.st_mtime_ns, st.st_size))
                except OSError:
                    continue
        except OSError:
            return

        if h == self._last_reactions_hash:
            return
        self._last_reactions_hash = h

        for m in self.messages_model.messages:
            new_reactions = get_reactions(
                self.shared_folder, self.current_chat_id, m["msg_id"]
            )
            self._reactions_cache[m["msg_id"]] = new_reactions
            if new_reactions != m.get("reactions", {}):
                self.messages_model.update_message_reactions(m["msg_id"], new_reactions)

    def _refresh_read_status_if_changed(self) -> None:
        if not self.current_chat_id:
            return

        from src.core.chat_logic import get_chat_recipients

        try:
            recipients = get_chat_recipients(self.shared_folder, self.current_chat_id)
            other_recipients = [fp for fp in recipients if fp != self.user.fp16]
        except Exception:
            return

        if not other_recipients:
            return

        read_by_users = {}
        for fp in other_recipients:
            read_by_users[fp] = set(get_read_messages(self.shared_folder, self.current_chat_id, fp))

        h = hash(tuple((fp, frozenset(msgs)) for fp, msgs in sorted(read_by_users.items())))
        if h == self._last_read_hash:
            return
        self._last_read_hash = h

        is_group = self.current_chat_id.startswith("grp_")

        for i, m in enumerate(self.messages_model.messages):
            if not m.get("is_me"):
                continue

            msg_id = m["msg_id"]

            # Определяем статус: True (все прочитали) или False
            if is_group:
                is_read_by_all = all(msg_id in read_by_users[fp] for fp in other_recipients)
            else:
                is_read_by_all = (msg_id in read_by_users[other_recipients[0]])

            # Передаем строку "all", если прочитано, иначе пустую строку
            new_status = "all" if is_read_by_all else ""

            if m.get("read_status") != new_status:
                m["read_status"] = new_status
                idx = self.messages_model.index(i)
                self.messages_model.dataChanged.emit(idx, idx, [Qt.UserRole])

    def _sync_and_render(self):
        if not self.current_chat_id:
            return

        # --- 1. Удалённые ---
        current_deleted = set(
            get_deleted_messages(self.shared_folder, self.current_chat_id, self.user.fp16)
        )
        if len(current_deleted) != self._last_deleted_count:
            self._last_deleted_count = len(current_deleted)
            to_remove = [
                m["msg_id"] for m in self.messages_model.messages
                if m["msg_id"] in current_deleted
            ]
            for mid in to_remove:
                self.messages_model.remove_message_by_id(mid)
                self.db.delete_message(mid)

        # --- 2. Новые файлы сообщений ---
        msg_dir = chat_message_dir(self.shared_folder, self.current_chat_id)
        if msg_dir.is_dir():
            current_count = len(list(msg_dir.glob("*.bin")))
            if current_count != self._last_file_count:
                self._last_file_count = current_count
                self._trigger_sync()

        # --- 3. Новые сообщения из БД ---
        msgs = self.db.get_messages_paginated(self.current_chat_id, 50, 0)
        if msgs:
            last_ts_in_model = (
                self.messages_model.messages[-1]["ts"]
                if self.messages_model.messages else 0
            )

            new_msgs = []
            incoming_to_mark = []

            for m in msgs:
                if m["ts"] <= last_ts_in_model:
                    continue
                new_msgs.append({
                    "msg_id": m["msg_id"],
                    "sender_fp16": m["sender_fp16"],
                    "text": m["text"],
                    "ts": m["ts"],
                    "is_me": (m["sender_fp16"] == self.user.fp16),
                    "read_status": "",  # Статус обновится ниже
                    "reactions": self._get_reactions_cached(m["msg_id"]),
                })
                if m["sender_fp16"] != self.user.fp16:
                    incoming_to_mark.append(m["msg_id"])

            if new_msgs:
                self.messages_model.add_messages(new_msgs)
                self.messages_view.scrollToBottom()
                if incoming_to_mark:
                    self.db.mark_messages_read(self.current_chat_id, incoming_to_mark)
                    mark_messages_read(
                        self.shared_folder, self.current_chat_id,
                        self.user.fp16, incoming_to_mark,
                    )

        # --- 4. Реакции и прочтения (только при изменении) ---
        self._refresh_reactions_if_changed()
        self._refresh_read_status_if_changed()

    def _trigger_sync(self):
        if self._sync_worker and self._sync_worker.isRunning():
            return

        self._sync_worker = SyncWorker(self.shared_folder, self.current_chat_id, self.user.fp16, self.user.priv_pem)

        def on_finished():
            if self._sync_worker in self._active_workers:
                self._active_workers.remove(self._sync_worker)

        self._sync_worker.finished.connect(on_finished)
        self._active_workers.append(self._sync_worker)
        self._sync_worker.start()

    def _on_send_clicked(self):
        if not self.current_chat_id:
            return

        text = self.input_field.text().strip()
        if not text:
            return

        self.input_field.clear()

        temp_ts = int(time.time() * 1000)
        temp_msg_id = f"pending_{temp_ts}_{self.user.fp16}"

        optimistic_msg = {
            "msg_id": temp_msg_id,
            "sender_fp16": self.user.fp16,
            "text": text,
            "ts": temp_ts,
            "is_me": True,
            "read_status": "",
            "reactions": {}
        }
        self.messages_model.add_messages([optimistic_msg])
        self.messages_view.scrollToBottom()

        worker = SendWorker(self.shared_folder, self.current_chat_id, self.user.fp16, self.user.priv_pem, text, self.db)

        def on_finished(success, real_id):
            if success:
                self.messages_model.remove_message_by_id(temp_msg_id)
                self._sync_and_render()
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось отправить сообщение")
                self.messages_model.remove_message_by_id(temp_msg_id)

            if worker in self._active_workers:
                self._active_workers.remove(worker)

        worker.finished.connect(on_finished)
        self._active_workers.append(worker)
        worker.start()

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
        self._update_selection_ui()

    def _update_selection_ui(self):
        self.lbl_selected.setText(f"Выбрано: {len(self.selected_msg_ids)}")

    def _toggle_message_selection(self, msg_id: str):
        if msg_id in self.selected_msg_ids:
            self.selected_msg_ids.remove(msg_id)
        else:
            self.selected_msg_ids.add(msg_id)
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

        msgs_to_delete = list(self.selected_msg_ids)
        for msg_id in msgs_to_delete:
            self.db.delete_message(msg_id)
            self.messages_model.remove_message_by_id(msg_id)

        self._exit_selection_mode()

        worker = DeleteWorker(
            self.shared_folder, self.current_chat_id,
            msgs_to_delete, self.user.fp16, for_everyone, self.db
        )
        self._active_workers.append(worker)
        worker.start()

    def _enter_selection_mode_and_select(self, msg_id):
        self._enter_selection_mode()
        self._toggle_message_selection(msg_id)

    def _on_title_clicked(self, event):
        if not self.current_chat_id:
            return
        meta = get_chat_meta(self.shared_folder, self.current_chat_id)
        if meta["type"] == "group":
            from src.ui.group_settings_view import GroupSettingsView
            self.group_window = GroupSettingsView(self.shared_folder, self.user, self.current_chat_id)
            self.group_window.show()

    def _on_chat_menu_clicked(self):
        if not self.current_chat_id:
            return

        menu = QMenu(self)

        act_clear_self = menu.addAction("🧹 Очистить историю (у себя)")
        act_clear_self.triggered.connect(self._clear_chat_history_self)

        act_clear_all = menu.addAction("🗑 Удалить историю (у обоих)")
        act_clear_all.triggered.connect(self._clear_chat_history_all)

        meta = get_chat_meta(self.shared_folder, self.current_chat_id)
        if meta["type"] == "group":
            keys = load_chat_keys(self.shared_folder, self.current_chat_id)
            wrapped = keys.get("wrapped", {})
            if self.user.fp16 in wrapped:
                group_key = unwrap_key(wrapped, self.user.fp16, self.user.priv_pem)
                enc = load_chat_meta_enc(self.shared_folder, self.current_chat_id)
                data = json.loads(enc.decode("utf-8"))
                if "nonce" in data and "ciphertext" in data:
                    aad = f"chat_id={self.current_chat_id}|meta".encode("utf-8")
                    decrypted = aes_decrypt(group_key, from_base64(data["nonce"]), from_base64(data["ciphertext"]), aad=aad)
                    group_meta = json.loads(decrypted.decode("utf-8"))

                    if group_meta.get("creator_fp16") == self.user.fp16:
                        menu.addSeparator()
                        act_delete_group = menu.addAction("💥 Удалить группу (у всех)")
                        act_delete_group.triggered.connect(self._delete_group_from_chat)

        menu.exec(self.btn_chat_menu.mapToGlobal(self.btn_chat_menu.rect().bottomLeft()))

    def _clear_chat_history_self(self):
        reply = QMessageBox.question(self, "Очистка", "Очистить историю чата у себя? (У собеседника останется)", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.db.delete_chat_messages(self.current_chat_id)
            self.messages_model.clear()
            QMessageBox.information(self, "Успех", "История очищена")

    def _clear_chat_history_all(self):
        reply = QMessageBox.question(
            self, "Удаление у всех",
            "Удалить ВСЮ историю чата у вас и у собеседника?\n"
            "Это действие необратимо.\n\n"
            "ВНИМАНИЕ: Сообщения будут ФИЗИЧЕСКИ УДАЛЕНЫ из сетевой папки!",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                from src.core.status import physically_delete_all_messages

                # 1. Физически стираем папку с сообщениями из шары
                physically_delete_all_messages(self.shared_folder, self.current_chat_id)

                # 2. Очищаем локальную БД
                self.db.delete_chat_messages(self.current_chat_id)

                # 3. Очищаем UI
                self.messages_model.clear()

                QMessageBox.information(self, "Успех", "Вся история физически удалена с шары")
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", str(e))

    def _delete_group_from_chat(self):
        reply = QMessageBox.question(
            self, "Удаление группы",
            "Вы уверены, что хотите ПОЛНОСТЬЮ удалить группу?\nВсе сообщения и файлы будут стерты.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                delete_group_chat(self.shared_folder, self.current_chat_id, self.user.fp16, self.user.priv_pem)
                QMessageBox.information(self, "Успех", "Группа удалена")
                self.messages_model.clear()
                self.current_chat_id = None
                self.label_title.setText("Выберите чат")
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", str(e))

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
        typing = status.get("typing", False) and status.get("typing_chat") == self.current_chat_id
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
            self.profile_window = ProfileView(self.shared_folder, self.user, target_fp16=self.current_other_fp)
            self.profile_window.show()
        elif meta["type"] == "group":
            from src.ui.group_settings_view import GroupSettingsView
            self.group_window = GroupSettingsView(self.shared_folder, self.user, self.current_chat_id)
            self.group_window.show()

    def _on_attach_clicked(self):
        if not self.current_chat_id:
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите файл")
        if file_path:
            try:
                send_file(self.shared_folder, self.current_chat_id, self.user.fp16, self.user.priv_pem, file_path)
                self._trigger_sync()
            except Exception as e:
                logger.error(f"Ошибка отправки файла: {e}")

    # ========================================================================
    # ЛЕВЫЙ КЛИК
    # ========================================================================
    def _on_message_left_click(self, index: QModelIndex):
        msg_data = index.data(Qt.UserRole)
        if not msg_data:
            return
        msg_id = msg_data["msg_id"]
        raw_text = msg_data["text"]

        if self.selection_mode:
            self._toggle_message_selection(msg_id)
            return

        if raw_text.startswith("[FILE]") and raw_text.endswith("[/FILE]"):
            inner = raw_text[6:-7]
            if "|" in inner:
                stored_name, original_name = inner.split("|", 1)
            else:
                stored_name = original_name = inner

            file_path = chat_files_dir(self.shared_folder, self.current_chat_id) / stored_name
            ext = stored_name.lower().split('.')[-1]

            if not file_path.exists():
                QMessageBox.warning(self, "Ошибка", "Файл не найден на диске.")
                return

            if ext in ('png', 'jpg', 'jpeg', 'gif', 'bmp'):
                try:
                    os.startfile(str(file_path))
                except Exception as e:
                    logger.error(f"Не удалось открыть изображение: {e}")
                    QMessageBox.warning(self, "Ошибка", f"Не удалось открыть файл: {e}")
            else:
                default_dir = self.db.get_setting("download_dir", str(Path.home() / "Downloads"))
                save_path = Path(default_dir) / original_name

                counter = 1
                while save_path.exists():
                    save_path = Path(default_dir) / f"{Path(original_name).stem} ({counter}){Path(original_name).suffix}"
                    counter += 1

                try:
                    Path(default_dir).mkdir(parents=True, exist_ok=True)
                    self._download_with_progress(file_path, save_path, original_name)
                except Exception as e:
                    QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить файл: {e}")
            return

    def _download_with_progress(self, src_path: Path, dest_path: Path, original_name: str):
        dialog = DownloadProgressDialog(original_name, self)
        worker = DownloadWorker(src_path, dest_path)

        worker.progress.connect(dialog.update_progress)

        def on_finished(success, error):
            dialog.accept()
            if success:
                QMessageBox.information(self, "Файл сохранён", f"Файл сохранён в:\n{dest_path}")
            else:
                QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить файл:\n{error}")
            if worker in self._active_workers:
                self._active_workers.remove(worker)

        worker.finished.connect(on_finished)
        self._active_workers.append(worker)

        dialog.show()
        worker.start()

    # ========================================================================
    # ПРАВЫЙ КЛИК
    # ========================================================================
    def _on_message_context_menu(self, pos: QPoint):
        index = self.messages_view.indexAt(pos)
        if not index.isValid():
            return

        msg_data = index.data(Qt.UserRole)
        msg_id = msg_data["msg_id"]
        raw_text = msg_data["text"]

        if raw_text.startswith("[FILE]") and raw_text.endswith("[/FILE]"):
            inner = raw_text[6:-7]
            if "|" in inner:
                stored_name, original_name = inner.split("|", 1)
            else:
                stored_name = original_name = inner

            file_path = chat_files_dir(self.shared_folder, self.current_chat_id) / stored_name
            ext = stored_name.lower().split('.')[-1]

            menu = QMenu(self)

            if ext in ('png', 'jpg', 'jpeg', 'gif', 'bmp'):
                action_open = menu.addAction("🖼 Открыть")
                action_open.triggered.connect(lambda: os.startfile(str(file_path)))

            action_save = menu.addAction("💾 Сохранить как...")
            action_save.triggered.connect(lambda: self._save_file_dialog(file_path, original_name))

            quick_emoji = self.db.get_setting("quick_reaction", "❤️")
            reactions = get_reactions(self.shared_folder, self.current_chat_id, msg_id)
            my_reaction = reactions.get(self.user.fp16)

            menu.addSeparator()
            if my_reaction:
                action_remove = menu.addAction(f"Убрать {my_reaction}")
                action_remove.triggered.connect(lambda: self._remove_reaction(msg_id))
                if my_reaction != quick_emoji:
                    action_quick = menu.addAction(f"Поставить {quick_emoji}")
                    action_quick.triggered.connect(lambda: self._set_reaction(msg_id, quick_emoji))
            else:
                action_quick = menu.addAction(f"Поставить {quick_emoji}")
                action_quick.triggered.connect(lambda: self._set_reaction(msg_id, quick_emoji))

            if reactions:
                action_show = menu.addAction("👀 Показать, кто поставил")
                action_show.triggered.connect(lambda: self._show_reaction_details(msg_id))

            menu.addSeparator()
            action_select = menu.addAction("☑️ Выбрать")
            action_select.triggered.connect(lambda: self._enter_selection_mode_and_select(msg_id))

            menu.exec(self.messages_view.mapToGlobal(pos))
            return

        if self.selection_mode:
            self._toggle_message_selection(msg_id)
            return

        self._show_message_menu(msg_id, self.messages_view.mapToGlobal(pos))

    def _save_file_dialog(self, file_path: Path, original_name: str):
        if not file_path.exists():
            QMessageBox.warning(self, "Ошибка", "Файл не найден на диске.")
            return

        default_dir = self.db.get_setting("download_dir", str(Path.home() / "Downloads"))

        save_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить файл",
            str(Path(default_dir) / original_name),
            "All Files (*)"
        )

        if save_path:
            try:
                shutil.copy2(file_path, save_path)
                QMessageBox.information(self, "Успех", f"Файл сохранён в:\n{save_path}")
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить файл: {e}")

    def _show_message_menu(self, msg_id: str, global_pos: QPoint):
        menu = QMenu(self)
        quick_emoji = self.db.get_setting("quick_reaction", "❤️")
        reactions = get_reactions(self.shared_folder, self.current_chat_id, msg_id)
        my_reaction = reactions.get(self.user.fp16)

        if not msg_id.startswith("pending_"):
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

            if reactions:
                menu.addSeparator()
                action_show = menu.addAction("👀 Показать, кто поставил")
                action_show.triggered.connect(lambda: self._show_reaction_details(msg_id))

        menu.addSeparator()
        action_select = menu.addAction("☑️ Выбрать")
        action_select.triggered.connect(lambda: self._enter_selection_mode_and_select(msg_id))

        menu.exec(global_pos)

    def _show_reaction_details(self, msg_id: str):
        reactions = get_reactions(self.shared_folder, self.current_chat_id, msg_id)
        if not reactions:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Реакции")
        dialog.resize(300, 400)
        layout = QVBoxLayout(dialog)

        list_widget = QListWidget()
        list_widget.setStyleSheet("""
            QListWidget { background-color: #1a1a2e; border: 1px solid #313148; border-radius: 8px; }
            QListWidget::item { padding: 8px; font-size: 14px; color: #cdd6f4; }
        """)

        from collections import defaultdict
        grouped = defaultdict(list)
        for fp16, emoji in reactions.items():
            grouped[emoji].append(fp16)

        for emoji, users in grouped.items():
            header = QListWidgetItem(f"{emoji} ({len(users)})")
            header.setFlags(Qt.NoItemFlags)
            header.setForeground(Qt.gray)
            list_widget.addItem(header)

            for user_fp in users:
                login = self.db.get_login_by_fp16(user_fp)
                item = QListWidgetItem(f"   👤 {login}")
                item.setFlags(Qt.NoItemFlags)
                list_widget.addItem(item)

        layout.addWidget(list_widget)
        dialog.exec()

    def _set_reaction(self, msg_id: str, emoji: str):
        try:
            set_reaction(
                self.shared_folder, self.current_chat_id, msg_id,
                self.user.fp16, emoji,
            )
        except Exception as e:
            logger.warning(f"Не удалось поставить реакцию: {e}")
            QMessageBox.warning(
                self, "Сеть",
                "Не удалось сохранить реакцию на сетевой папке.\n"
                "Попробуйте ещё раз через пару секунд.",
            )
            return
        self._sync_and_render()

    def _remove_reaction(self, msg_id: str):
        try:
            set_reaction(
                self.shared_folder, self.current_chat_id, msg_id,
                self.user.fp16, None,
            )
        except Exception as e:
            logger.warning(f"Не удалось убрать реакцию: {e}")
            QMessageBox.warning(
                self, "Сеть",
                "Не удалось обновить реакцию на сетевой папке.\n"
                "Попробуйте ещё раз через пару секунд.",
            )
            return
        self._sync_and_render()

    def _open_reaction_picker(self, msg_id: str):
        self._reaction_msg_id = msg_id
        pos = self.cursor().pos()
        self.reaction_picker.move(pos)
        self.reaction_picker.show()

    def _apply_reaction(self, emoji: str):
        if not self._reaction_msg_id or self._reaction_msg_id.startswith("pending_"):
            return
        try:
            reactions = get_reactions(self.shared_folder, self.current_chat_id, self._reaction_msg_id)
            if reactions.get(self.user.fp16) == emoji:
                set_reaction(self.shared_folder, self.current_chat_id, self._reaction_msg_id, self.user.fp16, None)
            else:
                set_reaction(self.shared_folder, self.current_chat_id, self._reaction_msg_id, self.user.fp16, emoji)
            self._sync_and_render()
        except Exception as e:
            logger.error(f"Ошибка установки реакции: {e}")
        finally:
            self._reaction_msg_id = None

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