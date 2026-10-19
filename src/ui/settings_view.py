"""Окно настроек Pygram."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTabWidget, QPushButton, QComboBox, QLineEdit, QSpinBox
)
from PySide6.QtCore import Qt, Signal


class SettingsView(QWidget):
    """Окно настроек (Персонализация и Аккаунты)."""

    settings_changed = Signal()

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Настройки Pygram")
        self.resize(600, 400)

        layout = QVBoxLayout(self)

        # Вкладки
        self.tabs = QTabWidget()

        # 1. Вкладка "Персонализация"
        self.tab_personal = QWidget()
        self._setup_personal_tab()
        self.tabs.addTab(self.tab_personal, "🎨 Персонализация")

        # 2. Вкладка "Аккаунты"
        self.tab_accounts = QWidget()
        self._setup_accounts_tab()
        self.tabs.addTab(self.tab_accounts, "👥 Аккаунты")

        layout.addWidget(self.tabs)

        # Кнопка сохранения
        btn_save = QPushButton("Сохранить настройки")
        btn_save.setStyleSheet("background-color: #4a90e2; color: white; padding: 10px; font-weight: bold;")
        btn_save.clicked.connect(self._on_save)
        layout.addWidget(btn_save)

    def _setup_personal_tab(self):
        layout = QVBoxLayout(self.tab_personal)

        # Шрифты
        font_group = QVBoxLayout()
        font_group.addWidget(QLabel("<b>Настройки шрифта</b>"))

        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Шрифт:"))
        self.combo_font = QComboBox()
        self.combo_font.addItems(["Segoe UI", "Arial", "Times New Roman", "Courier New", "Verdana"])
        font_row.addWidget(self.combo_font)

        font_row.addWidget(QLabel("Размер:"))
        self.spin_size = QSpinBox()
        self.spin_size.setRange(10, 24)
        self.spin_size.setValue(14)
        font_row.addWidget(self.spin_size)
        font_group.addLayout(font_row)

        layout.addLayout(font_group)
        layout.addSpacing(20)

        # Оформление (Кнопки)
        button_group = QVBoxLayout()
        button_group.addWidget(QLabel("<b>Оформление</b>"))

        button_group.addWidget(QLabel("Текст кнопки 'Отправить':"))
        self.input_btn_text = QLineEdit()
        self.input_btn_text.setPlaceholderText("Отправить")
        button_group.addWidget(self.input_btn_text)

        button_group.addWidget(QLabel("Подсказка в поле ввода:"))
        self.input_placeholder = QLineEdit()
        self.input_placeholder.setPlaceholderText("Введите сообщение...")
        button_group.addWidget(self.input_placeholder)

        layout.addLayout(button_group)
        layout.addSpacing(20)

        # Тема
        theme_group = QVBoxLayout()
        theme_group.addWidget(QLabel("<b>Тема оформления</b>"))
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["Темная (dark)", "Светлая (light)"])
        theme_group.addWidget(self.combo_theme)
        layout.addLayout(theme_group)

        layout.addStretch()

    def _setup_accounts_tab(self):
        layout = QVBoxLayout(self.tab_accounts)

        layout.addWidget(QLabel("<b>Активные аккаунты (до 3)</b>"))
        layout.addWidget(QLabel("Здесь будет список активных сессий."))

        # Кнопка добавления аккаунта
        btn_add = QPushButton("+ Войти в другой аккаунт")
        btn_add.setStyleSheet("background-color: #2a2a2a; padding: 10px;")
        layout.addWidget(btn_add)

        layout.addStretch()

    def _on_save(self):
        # Тут будет логика сохранения
        self.settings_changed.emit()
        self.close()