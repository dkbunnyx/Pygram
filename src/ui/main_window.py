"""Главное окно Pygram."""

from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QWidget, QVBoxLayout,
    QPushButton, QLabel, QFrame, QDialog, QListWidget, QListWidgetItem, QApplication
)
from PySide6.QtCore import Qt

from config import get_config
from src.ui.chat_list import ChatListWidget
from src.ui.chat_view import ChatViewWidget
from src.ui.settings_view import SettingsView
from src.core.chat_logic import get_all_users_fp16


class MainWindow(QMainWindow):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.config = get_config()
        self.admin_mode = False  # Режим просмотра всех чатов

        self.setWindowTitle(f"Pygram - {user.login} ({user.role})")
        self.resize(1000, 650)

        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Horizontal)

        # ==========================================
        # 1. САЙДБАР
        # ==========================================
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(60)

        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(5, 10, 5, 10)
        sidebar_layout.setSpacing(10)

        self.btn_settings = QPushButton("⚙️")
        self.btn_settings.setFixedSize(45, 45)
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.setToolTip("Настройки")
        self.btn_settings.clicked.connect(self._open_settings)
        sidebar_layout.addWidget(self.btn_settings)

        # Кнопки для админов
        if self.user.is_admin:
            self.btn_admin = QPushButton("🛡")
            self.btn_admin.setFixedSize(45, 45)
            self.btn_admin.setCursor(Qt.PointingHandCursor)
            self.btn_admin.setToolTip("Переключить админ-режим (Все чаты)")
            self.btn_admin.clicked.connect(self._toggle_admin_mode)
            sidebar_layout.addWidget(self.btn_admin)

            self.btn_manage_admins = QPushButton("👑")
            self.btn_manage_admins.setFixedSize(45, 45)
            self.btn_manage_admins.setCursor(Qt.PointingHandCursor)
            self.btn_manage_admins.setToolTip("Управление администраторами")
            self.btn_manage_admins.clicked.connect(self._open_admins_panel)
            sidebar_layout.addWidget(self.btn_manage_admins)

        sidebar_layout.addStretch()

        self.btn_profile = QPushButton("👤")
        self.btn_profile.setFixedSize(45, 45)
        self.btn_profile.setCursor(Qt.PointingHandCursor)
        self.btn_profile.setToolTip(f"Профиль: {self.user.login}")
        sidebar_layout.addWidget(self.btn_profile)

        # ==========================================
        # 2. СПИСОК ЧАТОВ
        # ==========================================
        self.chat_list = ChatListWidget(
            shared_folder=self.config.shared_folder,
            user_fp16=self.user.fp16,
            user_login=self.user.login,
            user_is_admin=self.admin_mode
        )
        self.chat_list.setMinimumWidth(250)
        self.chat_list.setMaximumWidth(400)

        # ==========================================
        # 3. ОКНО ЧАТА
        # ==========================================
        self.chat_view = ChatViewWidget(
            shared_folder=self.config.shared_folder,
            user=self.user
        )

        self.chat_list.chat_selected.connect(self.chat_view.load_chat)

        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.chat_list)
        self.splitter.addWidget(self.chat_view)

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 3)

        main_layout.addWidget(self.splitter)
        self.setCentralWidget(central)

        self._on_settings_saved()

    def _toggle_admin_mode(self):
        """Включает/выключает режим просмотра всех чатов."""
        self.admin_mode = not self.admin_mode
        self.chat_list.user_is_admin = self.admin_mode
        self.chat_list.refresh_chats()

        # Меняем цвет кнопки, чтобы было видно, что режим включен
        if self.admin_mode:
            self.btn_admin.setStyleSheet("background-color: #4a90e2;")
        else:
            self.btn_admin.setStyleSheet("")

    def _open_admins_panel(self):
        """Открывает панель управления админами (только для супер-админа)."""
        # Проверку на супер-админа сделаем внутри (по списку админов)

        dialog = QDialog(self)
        dialog.setWindowTitle("👑 Управление администраторами")
        dialog.resize(400, 500)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("<b>Все пользователи в шаре:</b>"))

        list_widget = QListWidget()
        users = get_all_users_fp16(self.config.shared_folder)

        from src.core.admin import is_admin
        from src.storage.local_db import LocalDB
        db = LocalDB()

        for fp in users:
            login = db.get_login_by_fp16(fp)
            status = " (Админ)" if is_admin(self.config.shared_folder, fp) else ""
            item = QListWidgetItem(f"{login}{status}")
            item.setData(Qt.UserRole, fp)
            list_widget.addItem(item)

        layout.addWidget(list_widget)
        dialog.exec()

    def _open_settings(self):
        self.settings_window = SettingsView(self.user)
        self.settings_window.settings_changed.connect(self._on_settings_saved)
        self.settings_window.show()

    def _on_settings_saved(self):
        from src.storage.local_db import LocalDB
        from PySide6.QtWidgets import QApplication, QWidget

        db = LocalDB()
        font_family = db.get_setting("font_family", "Segoe UI")
        font_size = int(db.get_setting("font_size", "14"))

        # 1. Меняем шрифт у самого приложения
        app = QApplication.instance()
        font = app.font()
        font.setFamily(font_family)
        font.setPointSize(font_size)
        app.setFont(font)

        # 2. Принудительно применяем шрифт ко ВСЕМ виджетам (рекурсивно)
        for widget in app.allWidgets():
            widget.setFont(font)

        # 3. Обновляем кнопку и плейсхолдер
        btn_text = db.get_setting("btn_text", "Отправить")
        placeholder = db.get_setting("placeholder", "Введите сообщение...")
        self.chat_view.btn_send.setText(btn_text)
        self.chat_view.input_field.setPlaceholderText(placeholder)