"""Экран быстрого входа для сохраненной сессии."""

from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from loguru import logger

from src.core.user import login_user


class SessionView(QWidget):
    """Экран ввода пароля для сохраненного аккаунта."""

    logged_in = Signal(object)
    switch_account = Signal()

    def __init__(self, session_data: dict, shared_folder: str, parent=None):
        super().__init__(parent)
        self.session_data = session_data
        self.shared_folder = shared_folder
        self.login = session_data["login"]
        self.fp16 = session_data["fp16"]
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(15)

        form_layout = QVBoxLayout()
        form_layout.setSpacing(10)
        form_layout.setContentsMargins(40, 40, 40, 40)

        # Аватарка
        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(80, 80)
        self.avatar_label.setAlignment(Qt.AlignCenter)

        avatar_path = Path(self.shared_folder) / ".profiles" / f"{self.fp16}.png"
        if avatar_path.exists():
            pixmap = QPixmap(str(avatar_path))
            self.avatar_label.setPixmap(pixmap.scaled(80, 80, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
            self.avatar_label.setStyleSheet("border-radius: 40px;")  # Круглая маска
        else:
            self.avatar_label.setText(self.login[0].upper())
            self.avatar_label.setStyleSheet("""
                background-color: #4a90e2; 
                color: white; 
                border-radius: 40px; 
                font-size: 36px; 
                font-weight: bold;
            """)

        form_layout.addWidget(self.avatar_label, alignment=Qt.AlignCenter)

        # Имя пользователя
        label_login = QLabel(self.login)
        label_login.setAlignment(Qt.AlignCenter)
        label_login.setStyleSheet("font-size: 20px; font-weight: bold;")
        form_layout.addWidget(label_login)

        # Поле пароля
        self.input_password = QLineEdit()
        self.input_password.setPlaceholderText("Введите пароль")
        self.input_password.setEchoMode(QLineEdit.Password)
        self.input_password.returnPressed.connect(self._on_login_clicked)
        form_layout.addWidget(self.input_password)

        # Кнопка входа
        self.btn_login = QPushButton("Войти")
        self.btn_login.clicked.connect(self._on_login_clicked)
        form_layout.addWidget(self.btn_login)

        # Кнопка "Другой аккаунт"
        self.btn_switch = QPushButton("Войти в другой аккаунт")
        self.btn_switch.setObjectName("btn_register")
        self.btn_switch.setCursor(Qt.PointingHandCursor)
        self.btn_switch.clicked.connect(self.switch_account.emit)
        form_layout.addWidget(self.btn_switch)

        layout.addLayout(form_layout)
        self.setFixedSize(400, 450)

    def _on_login_clicked(self):
        password = self.input_password.text()
        if not password:
            QMessageBox.warning(self, "Ошибка", "Введите пароль")
            return

        try:
            user = login_user(self.shared_folder, self.login, password)
            logger.info(f"Успешный вход через сессию: {self.login}")
            self.logged_in.emit(user)
        except ValueError as e:
            QMessageBox.warning(self, "Ошибка", str(e))
            self.input_password.clear()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка входа: {e}")
            logger.exception(e)