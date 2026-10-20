"""Окно входа и регистрации Pygram."""

from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QLineEdit, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from loguru import logger

from config import get_config
from src.core.user import login_user, register_user
from src.utils.validators import validate_login, validate_password
import src.ui


class LoginView(QWidget):
    """Экран входа и регистрации."""

    logged_in = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    def _auto_fill_login(self):
        """Автозаполняет логин, если есть сохраненная сессия."""
        from src.core.user import list_saved_sessions
        try:
            sessions = list_saved_sessions()
            if sessions:
                # Берем последнюю сессию
                last_session = sessions[-1]
                self.input_login.setText(last_session["login"])
                # Ставим курсор в поле пароля
                self.input_password.setFocus()
                logger.info(f"Автозаполнен логин: {last_session['login']}")
        except Exception as e:
            logger.error(f"Ошибка автозаполнения: {e}")

    def _auto_fill_login(self):
        """Автозаполняет логин, если есть сохраненная сессия."""
        from src.core.user import list_saved_sessions
        try:
            sessions = list_saved_sessions()
            if sessions:
                # Берем последнюю сессию
                last_session = sessions[-1]
                self.input_login.setText(last_session["login"])
                # Ставим курсор в поле пароля
                self.input_password.setFocus()
                logger.info(f"Автозаполнен логин: {last_session['login']}")
        except Exception as e:
            logger.error(f"Ошибка автозаполнения: {e}")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(15)

        form_layout = QVBoxLayout()
        form_layout.setSpacing(10)
        form_layout.setContentsMargins(40, 40, 40, 40)

        title = QLabel("Pygram")
        title.setObjectName("title_label")
        title.setAlignment(Qt.AlignCenter)
        form_layout.addWidget(title)

        self.input_login = QLineEdit()
        self.input_login.setPlaceholderText("Логин")
        form_layout.addWidget(self.input_login)

        self.input_password = QLineEdit()
        self.input_password.setPlaceholderText("Пароль (мин. 8 символов)")
        self.input_password.setEchoMode(QLineEdit.Password)
        self.input_password.returnPressed.connect(self._on_login_clicked)
        form_layout.addWidget(self.input_password)

        # Метка для вывода подсказок об ошибках
        self.label_error = QLabel("")
        self.label_error.setObjectName("error_label")
        self.label_error.setAlignment(Qt.AlignCenter)
        self.label_error.setWordWrap(True) # Чтобы длинный текст переносился
        form_layout.addWidget(self.label_error)

        self.btn_login = QPushButton("Войти")
        self.btn_login.clicked.connect(self._on_login_clicked)
        form_layout.addWidget(self.btn_login)

        self.btn_register = QPushButton("Создать аккаунт")
        self.btn_register.setObjectName("btn_register")
        self.btn_register.setCursor(Qt.PointingHandCursor)
        self.btn_register.clicked.connect(self._on_register_clicked)
        form_layout.addWidget(self.btn_register)

        layout.addLayout(form_layout)
        self.setFixedSize(400, 450)

    def _get_shared_folder(self):
        try:
            return get_config().shared_folder
        except Exception as e:
            self._show_error("Ошибка конфигурации. Проверьте .env")
            logger.error(f"Config error: {e}")
            return None

    def _show_error(self, text: str):
        self.label_error.setText(text)

    def _clear_error(self):
        self.label_error.setText("")

    def _validate_inputs(self, login: str, password: str) -> bool:
        """Проверяет логин и пароль. Возвращает True, если всё ок."""
        try:
            validate_login(login)
            validate_password(password)
            return True
        except ValueError as e:
            # Выводим точную подсказку от валидатора (например, "Логин: 3–32 символа...")
            self._show_error(str(e))
            return False

    def _on_login_clicked(self):
        self._clear_error()
        login = self.input_login.text().strip()
        password = self.input_password.text()

        if not login or not password:
            self._show_error("Введите логин и пароль")
            return

        # Проверяем формат перед отправкой на сервер
        if not self._validate_inputs(login, password):
            return

        shared_folder = self._get_shared_folder()
        if not shared_folder:
            return

        try:
            user = login_user(shared_folder, login, password)
            logger.info(f"Успешный вход: {login}")
            self.logged_in.emit(user)
        except FileNotFoundError:
            self._show_error("Пользователь не найден")
        except ValueError as e:
            self._show_error(str(e))
        except Exception as e:
            self._show_error("Ошибка сервера")
            logger.exception(e)

    def _on_register_clicked(self):
        self._clear_error()
        login = self.input_login.text().strip()
        password = self.input_password.text()

        if not login or not password:
            self._show_error("Введите логин и пароль")
            return

        # Строгая проверка формата логина и пароля
        if not self._validate_inputs(login, password):
            return

        shared_folder = self._get_shared_folder()
        if not shared_folder:
            return

        try:
            user = register_user(shared_folder, login, password)
            logger.info(f"Успешная регистрация: {login}")

            QMessageBox.information(
                self, "Успех",
                f"Аккаунт {login} создан!\nВы вошли в систему."
            )

            self.logged_in.emit(user)
        except FileExistsError:
            self._show_error("Этот логин уже занят")
        except Exception as e:
            self._show_error(str(e))
            logger.exception(e)