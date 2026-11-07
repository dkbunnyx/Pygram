"""Окно входа и регистрации Pygram."""

from pathlib import Path

from loguru import logger
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QMessageBox
)

from config import get_config
from src.core.trust import ensure_trusted_root, get_root_candidate
from src.core.user import login_user, register_user
from src.utils.validators import validate_login, validate_password


class LoginView(QWidget):
    """Экран входа и регистрации."""

    def eventFilter(self, watched, event):
        if watched is self.btn_password_eye and event.type() == QEvent.Leave:
            self.input_password.setEchoMode(QLineEdit.Password)

        return super().eventFilter(watched, event)

    logged_in = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

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

        password_layout = QHBoxLayout()
        password_layout.setSpacing(5)

        self.btn_password_eye = QPushButton("👁")
        self.btn_password_eye.setFixedWidth(42)
        self.btn_password_eye.setCursor(Qt.PointingHandCursor)
        self.btn_password_eye.setFocusPolicy(Qt.NoFocus)

        self.btn_password_eye.pressed.connect(
            lambda: self.input_password.setEchoMode(QLineEdit.Normal)
        )
        self.btn_password_eye.released.connect(
            lambda: self.input_password.setEchoMode(QLineEdit.Password)
        )

        self.btn_password_eye.installEventFilter(self)

        password_layout.addWidget(self.input_password)
        password_layout.addWidget(self.btn_password_eye)

        form_layout.addLayout(password_layout)

        # Метка для вывода подсказок об ошибках
        self.label_error = QLabel("")
        self.label_error.setObjectName("error_label")
        self.label_error.setAlignment(Qt.AlignCenter)
        self.label_error.setWordWrap(True)
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

    def _confirm_root_fingerprint(self, fingerprint: str) -> bool:
        grouped = " ".join(
            fingerprint[index : index + 4].upper()
            for index in range(0, len(fingerprint), 4)
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Проверка супер-администратора")
        box.setText(
            "На этом компьютере ещё не закреплён ключ супер-администратора.\n\n"
            "Сверьте ПОЛНЫЙ отпечаток ниже с отпечатком, показанным на первом компьютере.\n"
            "Если отличается хотя бы один символ — нажмите «Нет»."
        )
        box.setInformativeText(grouped)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        box.button(QMessageBox.Yes).setText("Совпадает")
        box.button(QMessageBox.No).setText("Не совпадает")
        return box.exec() == QMessageBox.Yes

    def _ensure_trusted_root(self, shared_folder: str) -> bool:
        try:
            candidate = ensure_trusted_root(
                shared_folder, self._confirm_root_fingerprint
            )
            self._first_computer_bootstrap = candidate is None
            return True
        except Exception as e:
            self._show_error(str(e))
            logger.warning(f"Проверка корня доверия не пройдена: {e}")
            return False

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
            self._show_error(str(e))
            return False

    def _on_login_clicked(self):
        self._clear_error()
        login = self.input_login.text().strip()
        password = self.input_password.text()

        if not login or not password:
            self._show_error("Введите логин и пароль")
            return

        if not self._validate_inputs(login, password):
            return

        shared_folder = self._get_shared_folder()
        if not shared_folder:
            return

        if not self._ensure_trusted_root(shared_folder):
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

        if not self._validate_inputs(login, password):
            return

        shared_folder = self._get_shared_folder()
        if not shared_folder:
            return

        if not self._ensure_trusted_root(shared_folder):
            return

        try:
            user = register_user(shared_folder, login, password)
            logger.info(f"Успешная регистрация: {login}")

            if getattr(self, "_first_computer_bootstrap", False):
                root = get_root_candidate(shared_folder)
                if root:
                    grouped = " ".join(
                        root["fingerprint"][index : index + 4].upper()
                        for index in range(0, len(root["fingerprint"]), 4)
                    )
                    QMessageBox.information(
                        self,
                        "Отпечаток супер-администратора",
                        "Сохраните этот ПОЛНЫЙ отпечаток. На каждом следующем компьютере "
                        "его нужно будет вручную сверить с показанным отпечатком.\n\n"
                        f"{grouped}",
                    )

            QMessageBox.information(
                self, "Успех", f"Аккаунт {login} создан!\nВы вошли в систему."
            )

            self.logged_in.emit(user)
        except FileExistsError:
            self._show_error("Этот логин уже занят")
        except Exception as e:
            self._show_error(str(e))
            logger.exception(e)
