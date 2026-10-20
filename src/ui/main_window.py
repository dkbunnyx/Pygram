"""Главное окно Pygram."""

from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QWidget, QVBoxLayout,
    QPushButton, QLabel, QFrame, QDialog, QListWidget,
    QListWidgetItem, QApplication, QMessageBox, QMenu
)
from PySide6.QtCore import Qt, QSize, QRectF, QTimer
from PySide6.QtGui import QPixmap, QIcon, QPainter, QBrush

from config import get_config
from src.ui.chat_list import ChatListWidget
from src.ui.chat_view import ChatViewWidget
from src.ui.settings_view import SettingsView
from src.ui.profile_view import ProfileView
from src.core.account_manager import AccountManager
from src.core.admin import (
    load_admins, is_super, is_admin, make_admin,
    remove_admin, toggle_manage_rights, toggle_read_rights,
    can_read_all_chats, can_manage_admins
)
from src.core.chat_logic import get_all_users_fp16
from src.core.status import set_online
from src.storage.local_db import LocalDB


class MainWindow(QMainWindow):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.config = get_config()
        self.admin_mode = False

        self.account_manager = AccountManager()
        self.account_manager.add_account(user)

        set_online(self.config.shared_folder, self.user.fp16, True)

        self.setWindowTitle(f"Pygram - {user.login} ({user.role})")
        self.resize(1000, 650)

        central = QWidget()
        central.setObjectName("main_window_bg")
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Horizontal)

        self._setup_sidebar()

        self.chat_list = ChatListWidget(
            shared_folder=self.config.shared_folder,
            user_fp16=self.user.fp16,
            user_login=self.user.login,
            user_priv_pem=self.user.priv_pem,
            user_is_admin=self.admin_mode
        )
        self.chat_list.setMinimumWidth(250)
        self.chat_list.setMaximumWidth(400)

        self.chat_view = ChatViewWidget(
            shared_folder=self.config.shared_folder,
            user=self.user
        )

        self.chat_list.chat_selected.connect(self._on_chat_selected)

        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.chat_list)
        self.splitter.addWidget(self.chat_view)

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 3)

        self.main_layout.addWidget(self.splitter)
        self.setCentralWidget(central)
        self._on_settings_saved()

        # Таймер для проверки новых сообщений и уведомлений
        self.notification_timer = QTimer(self)
        self.notification_timer.timeout.connect(self.chat_list.refresh_chats)
        self.notification_timer.start(5000)

    def _on_chat_selected(self, chat_id: str):
        """Загружает чат и обновляет список (чтобы убрать счетчик)."""
        self.chat_view.load_chat(chat_id)
        self.chat_list.refresh_chats()

    def closeEvent(self, event):
        set_online(self.config.shared_folder, self.user.fp16, False)
        event.accept()

    # ========================================================================
    # Сайдбар
    # ========================================================================

    def _setup_sidebar(self):
        if not hasattr(self, 'sidebar'):
            self.sidebar = QFrame()
            self.sidebar.setObjectName("sidebar")
            self.sidebar.setFixedWidth(60)
            self.sidebar_layout = QVBoxLayout(self.sidebar)
            self.sidebar_layout.setContentsMargins(5, 10, 5, 10)
            self.sidebar_layout.setSpacing(10)
        else:
            while self.sidebar_layout.count():
                item = self.sidebar_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        self.btn_settings = QPushButton("⚙️")
        self.btn_settings.setFixedSize(45, 45)
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.setToolTip("Настройки")
        self.btn_settings.clicked.connect(self._open_settings)
        self.sidebar_layout.addWidget(self.btn_settings)

        if can_read_all_chats(self.config.shared_folder, self.user.fp16):
            self.btn_admin = QPushButton("🛡")
            self.btn_admin.setFixedSize(45, 45)
            self.btn_admin.setCursor(Qt.PointingHandCursor)
            self.btn_admin.setToolTip("Переключить админ-режим")
            self.btn_admin.clicked.connect(self._toggle_admin_mode)
            self.sidebar_layout.addWidget(self.btn_admin)

        if can_manage_admins(self.config.shared_folder, self.user.fp16):
            self.btn_manage_admins = QPushButton("👑")
            self.btn_manage_admins.setFixedSize(45, 45)
            self.btn_manage_admins.setCursor(Qt.PointingHandCursor)
            self.btn_manage_admins.setToolTip("Управление администраторами")
            self.btn_manage_admins.clicked.connect(self._open_admins_panel)
            self.sidebar_layout.addWidget(self.btn_manage_admins)

        self.sidebar_layout.addStretch()

        self.btn_profile = QPushButton()
        self.btn_profile.setFixedSize(45, 45)
        self.btn_profile.setCursor(Qt.PointingHandCursor)
        self.btn_profile.setToolTip(f"Профиль: {self.user.login}")
        self.btn_profile.clicked.connect(self._open_profile)

        profile_dir = Path(self.config.shared_folder) / ".profiles"
        avatar_path = profile_dir / f"{self.user.fp16}.png"

        if avatar_path.exists():
            pixmap = QPixmap(str(avatar_path))
            rounded = QPixmap(45, 45)
            rounded.fill(Qt.transparent)

            painter = QPainter(rounded)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QBrush(pixmap.scaled(45, 45, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(0, 0, 45, 45))
            painter.end()

            self.btn_profile.setIcon(QIcon(rounded))
            self.btn_profile.setIconSize(QSize(45, 45))
            self.btn_profile.setStyleSheet("border: none; background: transparent;")
        else:
            self.btn_profile.setText("👤")
            self.btn_profile.setStyleSheet("font-size: 24px;")

        self.sidebar_layout.addWidget(self.btn_profile)

    def _open_profile(self):
        self.profile_window = ProfileView(self.config.shared_folder, self.user)
        self.profile_window.show()

    def _toggle_admin_mode(self):
        self.admin_mode = not self.admin_mode
        self.chat_list.user_is_admin = self.admin_mode
        self.chat_list.refresh_chats()

        if self.admin_mode:
            self.btn_admin.setStyleSheet("background-color: #4a90e2;")
        else:
            self.btn_admin.setStyleSheet("")

    # ========================================================================
    # Админ-панель
    # ========================================================================

    def _open_admins_panel(self):
        if not is_super(self.config.shared_folder, self.user.fp16):
            admins = load_admins(self.config.shared_folder)
            me = next((a for a in admins if a["fp16"] == self.user.fp16), None)
            if not me or not me.get("can_manage_admins", False):
                QMessageBox.warning(self, "Доступ", "У вас нет прав на управление администраторами.")
                return

        dialog = QDialog(self)
        dialog.setWindowTitle("👑 Управление администраторами")
        dialog.resize(400, 500)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("<b>Нажмите на пользователя для действий:</b>"))

        list_widget = QListWidget()
        list_widget.setStyleSheet("""
            QListWidget {
                background-color: #1a1a2e;
                border: 1px solid #313148;
                border-radius: 8px;
            }
            QListWidget::item {
                padding: 12px;
                font-size: 14px;
                color: #cdd6f4;
            }
            QListWidget::item:hover {
                background-color: #2a2a2a;
            }
            QListWidget::item:selected {
                background-color: #313148;
                color: #89b4fa;
            }
        """)

        def refresh_list():
            list_widget.clear()
            users = get_all_users_fp16(self.config.shared_folder)
            db = LocalDB()

            for fp in users:
                login = db.get_login_by_fp16(fp)
                is_adm = is_admin(self.config.shared_folder, fp)
                is_sup = is_super(self.config.shared_folder, fp)

                if is_sup:
                    text = f"👑 {login} (Супер-админ)"
                elif is_adm:
                    text = f"🛡 {login} (Админ)"
                else:
                    text = f"👤 {login} (Пользователь)"

                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, (fp, is_adm, is_sup))
                list_widget.addItem(item)

        def on_user_clicked(item):
            fp, is_adm, is_sup = item.data(Qt.UserRole)
            menu = QMenu(dialog)

            if not is_adm:
                action_promote = menu.addAction("Назначить администратором")
                action_promote.triggered.connect(
                    lambda: self._do_promote(fp, dialog, refresh_list)
                )
            elif not is_sup:
                admins = load_admins(self.config.shared_folder)
                entry = next((a for a in admins if a["fp16"] == fp), {})
                can_read = entry.get("can_read_all_chats", False)
                can_manage = entry.get("can_manage_admins", False)

                if is_super(self.config.shared_folder, self.user.fp16):
                    read_text = "❌ Запретить просмотр всех чатов" if can_read else "✅ Разрешить просмотр всех чатов"
                    action_read = menu.addAction(read_text)
                    action_read.triggered.connect(
                        lambda: self._toggle_read_rights(fp, dialog, refresh_list)
                    )

                    manage_text = "❌ Запретить выдачу админки" if can_manage else "✅ Разрешить выдачу админки"
                    action_manage = menu.addAction(manage_text)
                    action_manage.triggered.connect(
                        lambda: self._toggle_manage_rights(fp, dialog, refresh_list)
                    )

                    menu.addSeparator()

                action_demote = menu.addAction("⛔ Снять с админки")
                action_demote.triggered.connect(
                    lambda: self._do_demote(fp, dialog, refresh_list)
                )
            else:
                menu.addAction("👑 Это супер-админ. Действия недоступны").setEnabled(False)

            menu.exec(dialog.mapToGlobal(dialog.cursor().pos()))

        refresh_list()
        list_widget.itemClicked.connect(on_user_clicked)
        layout.addWidget(list_widget)
        dialog.exec()

    def _do_promote(self, fp: str, dialog: QDialog, refresh_callback):
        try:
            make_admin(self.config.shared_folder, fp, by=self.user.fp16, by_priv=self.user.priv_pem)
            QMessageBox.information(dialog, "Успех", "Пользователь назначен админом")
            refresh_callback()
        except Exception as e:
            QMessageBox.warning(dialog, "Ошибка", str(e))

    def _do_demote(self, fp: str, dialog: QDialog, refresh_callback):
        try:
            remove_admin(self.config.shared_folder, fp, by=self.user.fp16, by_priv=self.user.priv_pem)
            QMessageBox.information(dialog, "Успех", "Админ снят")
            refresh_callback()
        except Exception as e:
            QMessageBox.warning(dialog, "Ошибка", str(e))

    def _toggle_manage_rights(self, fp: str, dialog: QDialog, refresh_callback):
        try:
            toggle_manage_rights(self.config.shared_folder, fp, by=self.user.fp16)
            QMessageBox.information(dialog, "Успех", "Права на управление изменены")
            refresh_callback()
        except Exception as e:
            QMessageBox.warning(dialog, "Ошибка", str(e))

    def _toggle_read_rights(self, fp: str, dialog: QDialog, refresh_callback):
        try:
            toggle_read_rights(self.config.shared_folder, fp, by=self.user.fp16)
            QMessageBox.information(dialog, "Успех", "Права на просмотр чатов изменены")
            refresh_callback()
        except Exception as e:
            QMessageBox.warning(dialog, "Ошибка", str(e))

    # ========================================================================
    # Настройки / аккаунты
    # ========================================================================

    def _open_settings(self):
        self.settings_window = SettingsView(self.user, self.account_manager)
        self.settings_window.settings_changed.connect(self._on_settings_saved)
        self.settings_window.logout_requested.connect(self._on_logout_current)
        self.settings_window.switch_requested.connect(self._on_switch_account)
        self.settings_window.add_account_requested.connect(self._on_add_account)
        self.settings_window.show()

    def _on_switch_account(self, fp16: str):
        self.account_manager.switch_to(fp16)
        current = self.account_manager.get_current()
        if current:
            self._reload_for_user(current)

    def _on_logout_current(self):
        self.account_manager.remove_account(self.user.fp16)
        current = self.account_manager.get_current()
        if current:
            self._reload_for_user(current)
        else:
            self.close()

    def _on_add_account(self):
        from src.ui.login_view import LoginView
        self.login_window = LoginView()
        self.login_window.logged_in.connect(self._on_new_account_logged_in)
        self.login_window.show()

    def _on_new_account_logged_in(self, new_user):
        self.login_window.close()
        try:
            self.account_manager.add_account(new_user)
            self._reload_for_user(new_user)
        except ValueError as e:
            QMessageBox.warning(self, "Ошибка", str(e))

    def _reload_for_user(self, user):
        set_online(self.config.shared_folder, self.user.fp16, False)

        self.user = user
        self.setWindowTitle(f"Pygram - {user.login} ({user.role})")

        set_online(self.config.shared_folder, self.user.fp16, True)

        self._setup_sidebar()

        self.chat_list.user_fp16 = user.fp16
        self.chat_list.user_login = user.login
        self.chat_list.user_priv_pem = user.priv_pem
        self.chat_list.refresh_chats()

        self.chat_view.user = user
        self.chat_view.messages_list.clear()
        self.chat_view.input_widget.setVisible(False)
        self.chat_view.label_title.setText("Выберите чат")
        self.chat_view.label_status.setText("")
        self.chat_view.current_chat_id = None

    def _on_settings_saved(self):
        db = LocalDB()
        font_family = db.get_setting("font_family", "Segoe UI")
        font_size = int(db.get_setting("font_size", "14"))

        font = self.font()
        font.setFamily(font_family)
        font.setPointSize(font_size)
        QApplication.instance().setFont(font)

        btn_text = db.get_setting("btn_text", "Отправить")
        placeholder = db.get_setting("placeholder", "Введите сообщение...")
        emoji_btn = db.get_setting("emoji_button", "😊")

        self.chat_view.btn_send.setText(btn_text)
        self.chat_view.input_field.setPlaceholderText(placeholder)
        self.chat_view.btn_emoji.setText(emoji_btn)

        theme = db.get_setting("theme", "base")

        if theme == "custom":
            bg_color = db.get_setting("color_bg", "#1a1a2e")
            sidebar_bg = db.get_setting("color_sidebar_bg", "#1a1a1a")
            chat_list_bg = db.get_setting("color_chat_list_bg", "#1a1a2e")
            chat_bg = db.get_setting("color_chat_bg", "#1a1a2e")
            text_color = db.get_setting("color_text", "#cdd6f4")
            btn_bg = db.get_setting("color_btn_bg", "#252538")
            input_bg = db.get_setting("color_input_bg", "#252538")

            QApplication.instance().setStyleSheet(f"""
                QWidget {{
                    background-color: {bg_color};
                    color: {text_color};
                }}
                QLineEdit {{
                    background-color: {input_bg};
                    border: 1px solid #313148;
                    border-radius: 8px;
                    padding: 10px;
                    color: {text_color};
                }}
                QPushButton {{
                    background-color: {btn_bg};
                    border: 1px solid #313148;
                    border-radius: 8px;
                    color: {text_color};
                    padding: 10px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: #313148;
                }}
                #sidebar {{
                    background-color: {sidebar_bg};
                    border-right: 1px solid #2a2a2a;
                }}
                QTextBrowser {{
                    background-color: {chat_bg};
                    border: none;
                }}
                QScrollBar:vertical {{
                    background: {bg_color};
                    width: 10px;
                }}
                QScrollBar::handle:vertical {{
                    background: #313148;
                    border-radius: 5px;
                }}
            """)

            self.chat_list.list_widget.setStyleSheet(f"""
                QListWidget {{
                    background-color: {chat_list_bg};
                    border: none;
                }}
                QListWidget::item {{
                    color: {text_color};
                }}
                QListWidget::item:hover {{
                    background-color: #2a2a2a;
                }}
                QListWidget::item:selected {{
                    background-color: #313148;
                }}
            """)

            self.sidebar.setStyleSheet(f"""
                #sidebar {{
                    background-color: {sidebar_bg};
                    border-right: 1px solid #2a2a2a;
                }}
            """)

            for btn in self.chat_list.findChildren(QPushButton):
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {btn_bg};
                        color: {text_color};
                        border: 1px solid #313148;
                        border-radius: 8px;
                        padding: 10px;
                    }}
                    QPushButton:hover {{
                        background-color: #313148;
                    }}
                """)

            if self.chat_view.current_chat_id:
                self.chat_view.load_chat(self.chat_view.current_chat_id)
        else:
            from src.ui.theme import load_theme
            load_theme(QApplication.instance(), "base")

            self.chat_list.list_widget.setStyleSheet("")
            self.sidebar.setStyleSheet("")
            for btn in self.chat_list.findChildren(QPushButton):
                btn.setStyleSheet("")

            if self.chat_view.current_chat_id:
                self.chat_view.load_chat(self.chat_view.current_chat_id)