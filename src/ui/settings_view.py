"""Окно настроек Pygram."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTabWidget, QPushButton, QComboBox, QLineEdit, QSpinBox
)
from PySide6.QtCore import Qt, Signal
from src.storage.local_db import LocalDB

class SettingsView(QWidget):
    settings_changed = Signal()

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self._setup_ui()
        self._load_settings()  # <--- ЗАГРУЖАЕМ ПРИ ОТКРЫТИИ

    def _setup_ui(self):
        self.setWindowTitle("Настройки Pygram")
        self.resize(600, 450)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        # --- Вкладка 1: Персонализация ---
        self.tab_personal = QWidget()
        p_layout = QVBoxLayout(self.tab_personal)

        # Шрифты
        p_layout.addWidget(QLabel("<b>Настройки шрифта</b>"))
        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Шрифт:"))
        self.combo_font = QComboBox()
        self.combo_font.addItems(["Segoe UI", "Arial", "Times New Roman", "Courier New", "Verdana", "Tahoma"])
        font_row.addWidget(self.combo_font)

        font_row.addWidget(QLabel("Размер:"))
        self.spin_size = QSpinBox()
        self.spin_size.setRange(10, 28)
        font_row.addWidget(self.spin_size)
        p_layout.addLayout(font_row)
        p_layout.addSpacing(20)

        # Оформление
        p_layout.addWidget(QLabel("<b>Оформление</b>"))
        p_layout.addWidget(QLabel("Текст кнопки 'Отправить':"))
        self.input_btn_text = QLineEdit()
        p_layout.addWidget(self.input_btn_text)

        p_layout.addWidget(QLabel("Подсказка в поле ввода:"))
        self.input_placeholder = QLineEdit()
        p_layout.addWidget(self.input_placeholder)
        p_layout.addSpacing(20)

        # Тема
        p_layout.addWidget(QLabel("<b>Тема оформления</b>"))
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["Темная", "Светлая"])
        p_layout.addWidget(self.combo_theme)
        p_layout.addStretch()

        self.tabs.addTab(self.tab_personal, "🎨 Персонализация")

        # --- Вкладка 2: Аккаунты ---
        self.tab_accounts = QWidget()
        a_layout = QVBoxLayout(self.tab_accounts)
        a_layout.addWidget(QLabel("<b>Активные аккаунты (до 3)</b>"))
        a_layout.addWidget(QLabel("(Функция в разработке)"))
        a_layout.addStretch()
        self.tabs.addTab(self.tab_accounts, "👥 Аккаунты")

        layout.addWidget(self.tabs)

        btn_save = QPushButton("Сохранить настройки")
        btn_save.setStyleSheet("background-color: #4a90e2; color: white; padding: 10px; font-weight: bold;")
        btn_save.clicked.connect(self._on_save)
        layout.addWidget(btn_save)

    def _load_settings(self):
        db = LocalDB()
        self.combo_font.setCurrentText(db.get_setting("font_family", "Segoe UI"))
        self.spin_size.setValue(int(db.get_setting("font_size", "14")))
        self.input_btn_text.setText(db.get_setting("btn_text", "Отправить"))
        self.input_placeholder.setText(db.get_setting("placeholder", "Введите сообщение..."))

        theme = db.get_setting("theme", "dark")
        self.combo_theme.setCurrentIndex(0 if theme == "dark" else 1)

    def _on_save(self):
        db = LocalDB()
        db.set_setting("font_family", self.combo_font.currentText())
        db.set_setting("font_size", str(self.spin_size.value()))
        db.set_setting("btn_text", self.input_btn_text.text() or "Отправить")
        db.set_setting("placeholder", self.input_placeholder.text() or "Введите сообщение...")
        db.set_setting("theme", "dark" if "Темная" in self.combo_theme.currentText() else "light")

        self.settings_changed.emit()
        self.close()