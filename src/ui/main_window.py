"""Главное окно Pygram."""

from PySide6.QtWidgets import QMainWindow, QSplitter, QWidget, QVBoxLayout
from PySide6.QtCore import Qt

from config import get_config
from src.ui.chat_list import ChatListWidget
from src.ui.chat_view import ChatViewWidget


class MainWindow(QMainWindow):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.config = get_config()

        self.setWindowTitle(f"Pygram - {user.login} ({user.role})")
        self.resize(900, 600)

        # Главный виджет
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Сплиттер (слева чаты, справа переписка)
        splitter = QSplitter(Qt.Horizontal)

        # 1. Список чатов
        self.chat_list = ChatListWidget(
            shared_folder=self.config.shared_folder,
            user_fp16=self.user.fp16,
            user_login=self.user.login  # <--- ДОБАВИЛИ ЛОГИН
        )
        self.chat_list.setMinimumWidth(250)
        self.chat_list.setMaximumWidth(400)

        # 2. Окно переписки
        self.chat_view = ChatViewWidget(
            shared_folder=self.config.shared_folder,
            user=self.user
        )

        # Связываем клик по чату с загрузкой сообщений
        self.chat_list.chat_selected.connect(self.chat_view.load_chat)

        splitter.addWidget(self.chat_list)
        splitter.addWidget(self.chat_view)

        # Чтобы список чатов не растягивался
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        layout.addWidget(splitter)
        self.setCentralWidget(central)