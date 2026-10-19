"""Главное окно Pygram."""

from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QWidget, QVBoxLayout,
    QPushButton, QLabel, QFrame, QDialog, QListWidget,
    QListWidgetItem, QApplication, QMessageBox, QMenu
)
from PySide6.QtCore import Qt

from config import get_config
from src.ui.chat_list import ChatListWidget
from src.ui.chat_view import ChatViewWidget
from src.ui.settings_view import SettingsView
from src.core.account_manager import AccountManager
from src.core.admin import load_admins, is_super, is_admin, make_admin, remove_admin, toggle_manage_rights
from src.core.chat_logic import get_all_users_fp16
from src.storage.local_db import LocalDB


class MainWindow(QMainWindow):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.config = get_config()
        self.admin_mode = False

        self.account_manager = AccountManager()
        self.account_manager.add_account(user)

        self.setWindowTitle(f"Pygram - {user.login} ({user.role})")
        self.resize(1000, 650)

        central = QWidget()
        central.setObjectName("main_window_bg")
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Horizontal)

        # Создаем сайдбар (виджет)
        self._setup_sidebar()

        # Список чатов
        self.chat_list = ChatListWidget(
            shared_folder=self.config.shared_folder,
            user_fp16=self.user.fp16,
            user_login=self.user.login,
            user_is_admin=self.admin_mode
        )
        self.chat_list.setMinimumWidth(250)
        self.chat_list.setMaximumWidth(400)

        # Окно чата
        self.chat_view = ChatViewWidget(
            shared_folder=self.config.shared_folder,
            user=self.user
        )

        self.chat_list.chat_selected.connect(self.chat_view.load_chat)

        # Добавляем всё в сплиттер
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.chat_list)
        self.splitter.addWidget(self.chat_view)

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 3)

        self.main_layout.addWidget(self.splitter)
        self.setCentralWidget(central)
        self._on_settings_saved()

    def _setup_sidebar(self):
        """Создает или пересоздает виджет сайдбара."""
        if not hasattr(self, 'sidebar'):
            self.sidebar = QFrame()
            self.sidebar.setObjectName("sidebar")
            self.sidebar.setFixedWidth(60)
            self.sidebar_layout = QVBoxLayout(self.sidebar)
            self.sidebar_layout.setContentsMargins(5, 10, 5, 10)
            self.sidebar_layout.setSpacing(10)
        else:
            # Если сайдбар уже есть, очищаем его layout
            while self.sidebar_layout.count():
                item = self.sidebar_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        # Кнопка "Настройки"
        self.btn_settings = QPushButton("⚙️")
        self.btn_settings.setFixedSize(45, 45)
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.setToolTip("Настройки")
        self.btn_settings.clicked.connect(self._open_settings)
        self.sidebar_layout.addWidget(self.btn_settings)

        # Кнопки админа
        if self.user.is_admin:
            self.btn_admin = QPushButton("🛡")
            self.btn_admin.setFixedSize(45, 45)
            self.btn_admin.setCursor(Qt.PointingHandCursor)
            self.btn_admin.setToolTip("Переключить админ-режим")
            self.btn_admin.clicked.connect(self._toggle_admin_mode)
            self.sidebar_layout.addWidget(self.btn_admin)

            self.btn_manage_admins = QPushButton("👑")
            self.btn_manage_admins.setFixedSize(45, 45)
            self.btn_manage_admins.setCursor(Qt.PointingHandCursor)
            self.btn_manage_admins.setToolTip("Управление администраторами")
            self.btn_manage_admins.clicked.connect(self._open_admins_panel)
            self.sidebar_layout.addWidget(self.btn_manage_admins)

        self.sidebar_layout.addStretch()

        # Кнопка профиля
        self.btn_profile = QPushButton("👤")
        self.btn_profile.setFixedSize(45, 45)
        self.btn_profile.setCursor(Qt.PointingHandCursor)
        self.btn_profile.setToolTip(f"Профиль: {self.user.login}")
        self.sidebar_layout.addWidget(self.btn_profile)

    def _toggle_admin_mode(self):
        self.admin_mode = not self.admin_mode
        self.chat_list.user_is_admin = self.admin_mode
        self.chat_list.refresh_chats()

        if self.admin_mode:
            self.btn_admin.setStyleSheet("background-color: #4a90e2;")
        else:
            self.btn_admin.setStyleSheet("")

    def _open_admins_panel(self):
        """Открывает панель управления админами."""
        # Проверка прав (супер или can_manage)
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
                action_promote.triggered.connect(lambda: self._do_promote(fp, dialog))
            elif not is_sup:
                if is_super(self.config.shared_folder, self.user.fp16):
                    action_toggle = menu.addAction("Переключить право 'Управление админами'")
                    action_toggle.triggered.connect(lambda: self._toggle_rights(fp, dialog))
                    menu.addSeparator()

                action_demote = menu.addAction("Снять с админки")
                action_demote.triggered.connect(lambda: self._do_demote(fp, dialog))
            else:
                menu.addAction("Это супер-админ").setEnabled(False)

            menu.exec(dialog.mapToGlobal(dialog.cursor().pos()))

        list_widget.itemClicked.connect(on_user_clicked)
        layout.addWidget(list_widget)
        dialog.exec()

    def _do_promote(self, fp: str, dialog: QDialog):
        try:
            make_admin(self.config.shared_folder, fp, by=self.user.fp16, by_priv=self.user.priv_pem)
            QMessageBox.information(dialog, "Успех", "Пользователь назначен админом")
            dialog.accept()
        except Exception as e:
            QMessageBox.warning(dialog, "Ошибка", str(e))

    def _do_demote(self, fp: str, dialog: QDialog):
        try:
            remove_admin(self.config.shared_folder, fp, by=self.user.fp16, by_priv=self.user.priv_pem)
            QMessageBox.information(dialog, "Успех", "Админ снят")
            dialog.accept()
        except Exception as e:
            QMessageBox.warning(dialog, "Ошибка", str(e))

    def _toggle_rights(self, fp: str, dialog: QDialog):
        try:
            toggle_manage_rights(self.config.shared_folder, fp, by=self.user.fp16)
            QMessageBox.information(dialog, "Успех", "Права изменены")
            dialog.accept()
        except Exception as e:
            QMessageBox.warning(dialog, "Ошибка", str(e))

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
        self.user = user
        self.setWindowTitle(f"Pygram - {user.login} ({user.role})")

        # Пересоздаем кнопки в сайдбаре
        self._setup_sidebar()

        # Обновляем данные в chat_list и chat_view
        self.chat_list.user_fp16 = user.fp16
        self.chat_list.user_login = user.login
        self.chat_list.refresh_chats()

        self.chat_view.user = user
        self.chat_view.text_browser.clear()
        self.chat_view.input_widget.setVisible(False)

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
        self.chat_view.btn_send.setText(btn_text)
        self.chat_view.input_field.setPlaceholderText(placeholder)

        theme = db.get_setting("theme", "base")

        if theme == "custom":
            bg_color = db.get_setting("color_bg", "#1a1a2e")

            self.setStyleSheet(f"QMainWindow {{ background-color: {bg_color}; }}")
            self.centralWidget().setStyleSheet(f"QWidget#main_window_bg {{ background-color: {bg_color}; }}")
            self.sidebar.setStyleSheet(f"#sidebar {{ background-color: {bg_color}; border-right: 1px solid #2a2a2a; }}")
            self.chat_list.list_widget.setStyleSheet(f"QListWidget {{ background-color: {bg_color}; }}")

            if self.chat_view.current_chat_id:
                self.chat_view.load_chat(self.chat_view.current_chat_id)
        else:
            self.setStyleSheet("")
            self.centralWidget().setStyleSheet("")
            self.sidebar.setStyleSheet("")
            self.chat_list.list_widget.setStyleSheet("")
            if self.chat_view.current_chat_id:
                self.chat_view.load_chat(self.chat_view.current_chat_id)