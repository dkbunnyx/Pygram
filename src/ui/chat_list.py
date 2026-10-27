"""Виджет списка чатов Pygram."""

from pathlib import Path
import json
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget,
    QListWidgetItem, QPushButton, QInputDialog, QMessageBox
)
from PySide6.QtCore import Qt, Signal, QSize, QThread
from PySide6.QtGui import QColor, QIcon, QPixmap
from loguru import logger

from src.core.chat_logic import (
    list_user_chats, create_dm_chat, list_all_chats, create_group_chat,
    get_group_display_name,
)
from src.core.message import sync_messages_to_db
from src.storage.local_db import LocalDB
from src.storage.shared_store import load_chat_keys, load_chat_meta_enc
from src.os_integration.notifications import show_notification


class SyncAllWorker(QThread):
    """Фоновая синхронизация ВСЕХ чатов пользователя в локальную БД.

    Нужна для того, чтобы уведомления работали даже для чатов,
    которые сейчас НЕ открыты в ChatViewWidget.

    Раньше sync_messages_to_db вызывалась только для текущего
    открытого чата — из-за этого новые сообщения в других чатах
    не попадали в локальную БД, и get_unread_count() возвращал 0.
    """

    finished = Signal()

    def __init__(self, shared_folder, user_fp16: str, user_priv_pem: str, parent=None):
        super().__init__(parent)
        self.shared_folder = shared_folder
        self.user_fp16 = user_fp16
        self.user_priv_pem = user_priv_pem

    def run(self):
        try:
            chats = list_user_chats(self.shared_folder, self.user_fp16)
            logger.debug(
                f"[pid={os.getpid()}] SyncAllWorker: {len(chats)} чатов "
                f"для fp16={self.user_fp16}"
            )
            for chat in chats:
                chat_id = chat["chat_id"]
                try:
                    sync_messages_to_db(
                        self.shared_folder,
                        chat_id,
                        self.user_fp16,
                        self.user_priv_pem,
                        prune_missing=False,  # ← НЕ удаляем чужие записи
                    )
                except Exception as e:
                    logger.warning(f"SyncAllWorker: ошибка синхронизации {chat_id}: {e}")
        except Exception as e:
            logger.error(f"SyncAllWorker: критическая ошибка: {e}")
        finally:
            self.finished.emit()


class ChatListWidget(QWidget):
    """Список чатов пользователя."""

    chat_selected = Signal(str)

    def __init__(
        self,
        shared_folder: str | Path,
        user_fp16: str,
        user_login: str,
        user_priv_pem: str = "",
        user_is_admin: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.shared_folder = shared_folder
        self.user_fp16 = user_fp16
        self.user_login = user_login
        self.user_priv_pem = user_priv_pem
        self.user_is_admin = user_is_admin
        self.profile_dir = Path(shared_folder) / ".profiles"
        self._last_unread: dict[str, int] = {}
        self.db = LocalDB()

        self.current_open_chat_id: str | None = None

        # Воркер фоновой синхронизации всех чатов
        self._sync_all_worker: SyncAllWorker | None = None
        # Флаг: идёт ли сейчас синхронизация (чтобы не дёргать уведомления
        # на неполных данных)
        self._sync_in_progress: bool = False

        # СИНХРОНИЗАЦИЯ ЛОГИНОВ ПРИ ЗАПУСКЕ
        self._sync_user_logins()

        self._setup_ui()
        self._sync_in_progress = True  # ← на время первой синхронизации
        self.refresh_chats()  # ← отрисует чаты, но не будет проверять уведомления
        self.sync_all_chats()  # ← в _on_sync_all_finished сбросит флаг и вызовет refresh_chats

    # ========================================================================
    # СМЕНА ПОЛЬЗОВАТЕЛЯ
    # ========================================================================

    def set_user(self, user_fp16: str, user_login: str, user_priv_pem: str) -> None:
        """Корректно переключает виджет на другого пользователя.

        Сбрасывает _last_unread (иначе старые счётчики от предыдущего
        аккаунта ломают логику уведомлений) и current_open_chat_id.
        """
        logger.info(
            f"[pid={os.getpid()}] ChatList.set_user: "
            f"{self.user_login} -> {user_login} (fp16={user_fp16})"
        )
        self.user_fp16 = user_fp16
        self.user_login = user_login
        self.user_priv_pem = user_priv_pem
        self._last_unread.clear()
        self.current_open_chat_id = None
        self._sync_user_logins()
        self.refresh_chats()
        self.sync_all_chats()

    # ========================================================================
    # СИНХРОНИЗАЦИЯ ВСЕХ ЧАТОВ
    # ========================================================================

    def sync_all_chats(self) -> None:
        """Запускает фоновую синхронизацию всех чатов пользователя.

        Если синхронизация уже идёт — второй запуск игнорируется.
        """
        if self._sync_all_worker and self._sync_all_worker.isRunning():
            logger.debug(f"[pid={os.getpid()}] sync_all_chats: уже идёт, пропуск")
            return

        self._sync_in_progress = True
        self._sync_all_worker = SyncAllWorker(
            self.shared_folder,
            self.user_fp16,
            self.user_priv_pem,
        )
        self._sync_all_worker.finished.connect(self._on_sync_all_finished)
        self._sync_all_worker.start()

    def _on_sync_all_finished(self) -> None:
        self._sync_in_progress = False
        if self._sync_all_worker:
            self._sync_all_worker.deleteLater()
            self._sync_all_worker = None
        self.refresh_chats()

    # ========================================================================
    # СИНХРОНИЗАЦИЯ ЛОГИНОВ
    # ========================================================================

    def _sync_user_logins(self) -> None:
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

    # ========================================================================
    # UI
    # ========================================================================

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

    # ========================================================================
    # ОБНОВЛЕНИЕ СПИСКА
    # ========================================================================

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

                # Проверяем уведомления только если синхронизация завершена —
                # иначе на неполных данных можно пропустить или задвоить уведомление
                if not self._sync_in_progress:
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

    # ========================================================================
    # УВЕДОМЛЕНИЯ
    # ========================================================================

    def _check_new_messages(self, chats: list[dict]):
        for chat in chats:
            chat_id = chat["chat_id"]
            unread = self.db.get_unread_count(chat_id, self.user_fp16)

            old_count = self._last_unread.get(chat_id, 0)

            # Диагностический лог — видно, почему не срабатывает уведомление
            if unread != old_count:
                logger.info(
                    f"[pid={os.getpid()}] [{self.user_login}] "
                    f"chat={chat_id} unread={unread} old={old_count} "
                    f"db={self.db.path}"
                )

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

                logger.info(f"ВЫЗОВ УВЕДОМЛЕНИЯ: {title} - {unread} новых")
                show_notification(
                    title=title,
                    message=f"Новых сообщений: {unread}",
                )

            self._last_unread[chat_id] = unread

    # ========================================================================
    # ОБРАБОТЧИКИ
    # ========================================================================

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