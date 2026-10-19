"""Главное окно Pygram."""

from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QWidget, QVBoxLayout,
    QPushButton, QLabel, QFrame
)
from PySide6.QtCore import Qt

from config import get_config
from src.ui.chat_list import ChatListWidget
from src.ui.chat_view import ChatViewWidget
from src.ui.settings_view import SettingsView


class MainWindow(QMainWindow):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.config = get_config()

        self.setWindowTitle(f"Pygram - {user.login} ({user.role})")
        self.resize(1000, 650)  # Сделали окно чуть шире

        # Главный контейнер
        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Сплиттер для 3-х колонок
        self.splitter = QSplitter(Qt.Horizontal)

        # ==========================================
        # 1. САЙДБАР (Левая узкая панель)
        # ==========================================
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(60)

        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(5, 10, 5, 10)
        sidebar_layout.setSpacing(10)

        # Кнопка "Настройки"
        self.btn_settings = QPushButton("⚙️")
        self.btn_settings.setFixedSize(45, 45)
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.setToolTip("Настройки")
        self.btn_settings.clicked.connect(self._open_settings)
        sidebar_layout.addWidget(self.btn_settings)

        # Отступ, чтобы остальные кнопки ушли вниз
        sidebar_layout.addStretch()

        # Кнопка "Профиль" (заглушка)
        self.btn_profile = QPushButton("👤")
        self.btn_profile.setFixedSize(45, 45)
        self.btn_profile.setCursor(Qt.PointingHandCursor)
        self.btn_profile.setToolTip(f"Профиль: {self.user.login}")
        sidebar_layout.addWidget(self.btn_profile)

        # ==========================================
        # 2. СПИСОК ЧАТОВ (Средняя панель)
        # ==========================================
        self.chat_list = ChatListWidget(
            shared_folder=self.config.shared_folder,
            user_fp16=self.user.fp16,
            user_login=self.user.login
        )
        self.chat_list.setMinimumWidth(250)
        self.chat_list.setMaximumWidth(400)

        # ==========================================
        # 3. ОКНО ЧАТА (Правая панель)
        # ==========================================
        self.chat_view = ChatViewWidget(
            shared_folder=self.config.shared_folder,
            user=self.user
        )

        # Связываем клик по чату с загрузкой сообщений
        self.chat_list.chat_selected.connect(self.chat_view.load_chat)

        # Добавляем всё в сплиттер
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.chat_list)
        self.splitter.addWidget(self.chat_view)

        # Пропорции: сайдбар фиксирован, список чатов 1 часть, чат 3 части
        self.splitter.setStretchFactor(0, 0)  # Сайдбар не растягивается
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 3)

        main_layout.addWidget(self.splitter)
        self.setCentralWidget(central)

    def _open_settings(self):
        """Открывает окно настроек."""
        self.settings_window = SettingsView(self.user)
        self.settings_window.settings_changed.connect(self._on_settings_saved)
        self.settings_window.show()

    def _on_settings_saved(self):
        """Вызывается, когда пользователь нажал 'Сохранить' в настройках."""
        # Пока просто заглушка, позже тут будет применение шрифтов и тем
        pass