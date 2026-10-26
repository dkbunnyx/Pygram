"""Виджет списка чатов Pygram."""

from pathlib import Path
import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget,
    QListWidgetItem, QPushButton, QInputDialog, QMessageBox
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QIcon, QPixmap
from loguru import logger

from src.core.chat_logic import (
    list_user_chats, create_dm_chat, list_all_chats, create_group_chat,
    get_group_display_name,
)
from src.storage.local_db import LocalDB
from src.storage.shared_store import load_chat_keys, load_chat_meta_enc
from src.os_integration.notifications import show_notification


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
        self.profile_dir = Path(shared_folder) / ".profiles"
        self._last_unread = {}
        self.db = LocalDB()

        self.current_open_chat_id: str | None = None

        # СИНХРОНИЗАЦИЯ ЛОГИНОВ ПРИ ЗАПУСКЕ
        self._sync_user_logins()

        self._setup_ui()
        self.refresh_chats()

    def _sync_user_logins(self):
        """Сканирует маркеры логинов в шаре и обновляет локальную БД."""
        logins_dir = Path(self.shared_folder) / ".logins"
        if not logins_dir.exists():
            return

        for marker_file in logins_dir.glob("*"):
            try:
                data = json.loads(marker_file.read_text(encoding="utf-8"))
                fp = data.get("fp")
                login = data.get("login")
                if fp and login:
                    fp16 = fp[:16]
                    self.db.save_user_map(fp16, login)
            except Exception:
                pass

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
        self.list_widget.setIconSize(QSize(24, 24))
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list_widget)

    def _group_name_or_default(self, chat_id: str) -> str:
        return get_group_display_name(
            self.shared_folder, chat_id, self.user_fp16, self.user_priv_pem,
            default=f"Группа {chat_id[4:12]}",
        ) or f"Группа {chat_id[4:12]}"

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
                    self._add_chat_item(chat, show_unread=True)
                self._check_new_messages(chats)

                if not self.current_open_chat_id:
                    first_chat_id = chats[0]["chat_id"]
                    self.current_open_chat_id = first_chat_id
                    for i in range(self.list_widget.count()):
                        item = self.list_widget.item(i)
                        if item.data(Qt.UserRole) == first_chat_id:
                            self.list_widget.setCurrentItem(item)
                            break
                    self.chat_selected.emit(first_chat_id)

            if self.user_is_admin:
                header_all = QListWidgetItem("СПИСОК ВСЕХ ЧАТОВ: ")
                header_all.setFlags(Qt.NoItemFlags)
                header_all.setForeground(QColor("gray"))
                self.list_widget.addItem(header_all)

                all_chats = list_all_chats(self.shared_folder)
                my_chat_ids = [c["chat_id"] for c in chats]

                for chat in all_chats:
                    if chat["chat_id"] not in my_chat_ids:
                        self._add_chat_item(chat, prefix="  ", show_unread=False)

        except Exception as e:
            logger.error(f"Ошибка загрузки чатов: {e}")

    def _add_chat_item(self, chat: dict, prefix: str = "", show_unread: bool = True):
        chat_id = chat["chat_id"]
        chat_type = chat["type"]

        icon = None
        display_name = chat_id

        if chat_type == "dm":
            parts = chat_id.replace("dm_", "").split("__")
            if len(parts) == 2:
                fp1, fp2 = parts
                other_fp = fp1 if fp2 == self.user_fp16 else fp2

                display_name = self.db.get_login_by_fp16(other_fp)
                if display_name == other_fp[:8]:
                    display_name = f"Чат {other_fp[:8]}"

                avatar_path = self.profile_dir / f"{other_fp}.png"
                if avatar_path.exists():
                    icon = QIcon(str(avatar_path))
            else:
                display_name = "Личный чат"

        elif chat_type == "group":
            display_name = self._group_name_or_default(chat_id)

            avatar_path = self.profile_dir / f"{chat_id}.png"
            if avatar_path.exists():
                icon = QIcon(str(avatar_path))
            else:
                display_name = f"👥 {display_name}"

        elif chat_type == "favorites":
            owner_fp = chat_id.replace("fav_", "")
            owner_login = self.db.get_login_by_fp16(owner_fp)
            if prefix:
                display_name = f"⭐ Избранное {owner_login}"
            else:
                display_name = "⭐ Избранное"

        elif chat_type == "admin_chat":
            display_name = "🛡 Админ-чат"

        if show_unread and chat_id != self.current_open_chat_id:
            unread = self.db.get_unread_count(chat_id, self.user_fp16)
            if unread > 0:
                display_name = f"{display_name} ({unread})"

        text = f"{prefix}{display_name}"
        item = QListWidgetItem(text)

        if icon:
            item.setIcon(icon)

        item.setData(Qt.UserRole, chat_id)
        self.list_widget.addItem(item)

    def _check_new_messages(self, chats: list[dict]):
        for chat in chats:
            chat_id = chat["chat_id"]
            unread = self.db.get_unread_count(chat_id, self.user_fp16)

            old_count = self._last_unread.get(chat_id, 0)
            if unread > old_count:
                if chat_id == self.current_open_chat_id:
                    self._last_unread[chat_id] = unread
                    continue

                chat_type = chat["type"]
                if chat_type == "dm":
                    parts = chat_id.replace("dm_", "").split("__")
                    if len(parts) == 2:
                        fp1, fp2 = parts
                        other_fp = fp1 if fp2 == self.user_fp16 else fp2
                        title = self.db.get_login_by_fp16(other_fp)
                    else:
                        title = "Личный чат"
                elif chat_type == "group":
                    title = self._group_name_or_default(chat_id)
                elif chat_type == "favorites":
                    title = "Избранное"
                elif chat_type == "admin_chat":
                    title = "Админ-чат"
                else:
                    title = chat_id

                show_notification(
                    title=title,
                    message=f"Новых сообщений: {unread}",
                )

            self._last_unread[chat_id] = unread

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

                from src.core.identity import get_fp16
                other_fp = get_fp16(self.shared_folder, login)
                if other_fp:
                    self.db.save_user_map(other_fp, login)

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

            self.db.save_chat_cache(chat_id, "group", name)

            self.refresh_chats()

            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                if item.data(Qt.UserRole) == chat_id:
                    self.list_widget.setCurrentItem(item)
                    self.chat_selected.emit(chat_id)
                    break
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", str(e))