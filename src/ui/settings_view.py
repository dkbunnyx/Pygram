"""Окно настроек Pygram."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTabWidget, QPushButton, QComboBox, QLineEdit, QSpinBox, QColorDialog, QListWidget, QMessageBox, QListWidgetItem
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from src.storage.local_db import LocalDB


class SettingsView(QWidget):
    settings_changed = Signal()
    logout_requested = Signal()
    switch_requested = Signal(str)
    add_account_requested = Signal()

    def __init__(self, user, account_manager, parent=None):
        super().__init__(parent)
        self.user = user
        self.account_manager = account_manager
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        self.setWindowTitle("Настройки Pygram")
        self.resize(600, 650)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        # --- Вкладка 1: Персонализация ---
        self.tab_personal = QWidget()
        p_layout = QVBoxLayout(self.tab_personal)

        p_layout.addWidget(QLabel("<b>Тема оформления</b>"))
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["Основная (темная)", "Пользовательская"])
        self.combo_theme.currentTextChanged.connect(self._on_theme_changed)
        p_layout.addWidget(self.combo_theme)
        p_layout.addSpacing(10)

        self.colors_widget = QWidget()
        c_layout = QVBoxLayout(self.colors_widget)
        c_layout.setContentsMargins(0, 0, 0, 0)

        c_layout.addWidget(QLabel("<b>Настройка цветов</b>"))

        self.btn_bg = QPushButton("Цвет фона приложения (сайдбар, списки)")
        self.btn_bg.clicked.connect(lambda: self._pick_color("color_bg", self.btn_bg))
        c_layout.addWidget(self.btn_bg)

        self.btn_chat_bg = QPushButton("Цвет фона окна сообщений")
        self.btn_chat_bg.clicked.connect(lambda: self._pick_color("color_chat_bg", self.btn_chat_bg))
        c_layout.addWidget(self.btn_chat_bg)

        self.btn_my = QPushButton("Цвет моих сообщений")
        self.btn_my.clicked.connect(lambda: self._pick_color("color_my_msg", self.btn_my))
        c_layout.addWidget(self.btn_my)

        self.btn_other = QPushButton("Цвет сообщений собеседника")
        self.btn_other.clicked.connect(lambda: self._pick_color("color_other_msg", self.btn_other))
        c_layout.addWidget(self.btn_other)

        self.colors_widget.setVisible(False)
        p_layout.addWidget(self.colors_widget)
        p_layout.addSpacing(10)

        p_layout.addWidget(QLabel("<b>Настройки шрифта</b>"))
        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Шрифт:"))
        self.combo_font = QComboBox()
        self.combo_font.addItems(["Segoe UI", "Arial", "Times New Roman", "Courier New", "Verdana"])
        font_row.addWidget(self.combo_font)

        font_row.addWidget(QLabel("Размер:"))
        self.spin_size = QSpinBox()
        self.spin_size.setRange(10, 28)
        font_row.addWidget(self.spin_size)
        p_layout.addLayout(font_row)
        p_layout.addSpacing(10)

        p_layout.addWidget(QLabel("<b>Оформление</b>"))
        p_layout.addWidget(QLabel("Текст кнопки 'Отправить':"))
        self.input_btn_text = QLineEdit()
        p_layout.addWidget(self.input_btn_text)

        p_layout.addWidget(QLabel("Подсказка в поле ввода:"))
        self.input_placeholder = QLineEdit()
        p_layout.addWidget(self.input_placeholder)

        # --- ЭМОДЗИ ДЛЯ КНОПКИ ---
        p_layout.addWidget(QLabel("Эмодзи для кнопки чата:"))
        emoji_row = QHBoxLayout()
        self.btn_emoji_picker = QPushButton("😊")
        self.btn_emoji_picker.setFixedSize(50, 40)
        self.btn_emoji_picker.clicked.connect(self._on_pick_emoji)
        emoji_row.addWidget(self.btn_emoji_picker)
        emoji_row.addStretch()
        p_layout.addLayout(emoji_row)

        p_layout.addStretch()

        self.tabs.addTab(self.tab_personal, "🎨 Персонализация")

        # --- Вкладка 2: Аккаунты ---
        self.tab_accounts = QWidget()
        a_layout = QVBoxLayout(self.tab_accounts)
        a_layout.addWidget(QLabel("<b>Активные аккаунты (до 3)</b>"))

        self.accounts_list = QListWidget()
        self.accounts_list.itemClicked.connect(self._on_account_clicked)
        a_layout.addWidget(self.accounts_list)

        btn_add = QPushButton("+ Войти в другой аккаунт")
        btn_add.clicked.connect(self._on_add_account)
        a_layout.addWidget(btn_add)

        btn_logout = QPushButton("Выйти из текущего аккаунта")
        btn_logout.clicked.connect(self._on_logout)
        a_layout.addWidget(btn_logout)

        a_layout.addStretch()
        self.tabs.addTab(self.tab_accounts, "👥 Аккаунты")

        layout.addWidget(self.tabs)

        btn_save = QPushButton("Сохранить настройки")
        btn_save.setStyleSheet("background-color: #4a90e2; color: white; padding: 10px; font-weight: bold;")
        btn_save.clicked.connect(self._on_save)
        layout.addWidget(btn_save)

    def _on_theme_changed(self, text):
        is_custom = "Пользовательская" in text
        self.colors_widget.setVisible(is_custom)

    def _load_settings(self):
        db = LocalDB()
        self.combo_font.setCurrentText(db.get_setting("font_family", "Segoe UI"))
        self.spin_size.setValue(int(db.get_setting("font_size", "14")))
        self.input_btn_text.setText(db.get_setting("btn_text", "Отправить"))
        self.input_placeholder.setText(db.get_setting("placeholder", "Введите сообщение..."))

        theme = db.get_setting("theme", "base")
        self.combo_theme.setCurrentIndex(0 if theme == "base" else 1)

        self._update_btn_color(self.btn_bg, db.get_setting("color_bg", "#1a1a2e"))
        self._update_btn_color(self.btn_chat_bg, db.get_setting("color_chat_bg", "#1a1a2e"))
        self._update_btn_color(self.btn_my, db.get_setting("color_my_msg", "#4a90e2"))
        self._update_btn_color(self.btn_other, db.get_setting("color_other_msg", "#e2a04a"))

        self._on_theme_changed(self.combo_theme.currentText())

        # Загружаем эмодзи для кнопки
        self.btn_emoji_picker.setText(db.get_setting("emoji_button", "😊"))

        self.accounts_list.clear()
        for acc in self.account_manager.accounts:
            prefix = "👉 " if acc.fp16 == self.user.fp16 else "    "
            item = QListWidgetItem(f"{prefix}{acc.login}")
            item.setData(Qt.UserRole, acc.fp16)
            self.accounts_list.addItem(item)

    def _update_btn_color(self, button, color_hex):
        button.setStyleSheet(f"background-color: {color_hex}; color: white; padding: 5px;")

    def _pick_color(self, setting_key: str, button):
        db = LocalDB()
        current = db.get_setting(setting_key, "#000000")
        color = QColorDialog.getColor(QColor(current), self, "Выберите цвет")
        if color.isValid():
            hex_color = color.name()
            db.set_setting(setting_key, hex_color)
            self._update_btn_color(button, hex_color)

    def _on_pick_emoji(self):
        from src.ui.widgets.emoji_picker import EmojiPicker

        picker = EmojiPicker()
        picker.emoji_selected.connect(self._set_emoji_button)

        pos = self.btn_emoji_picker.mapToGlobal(self.btn_emoji_picker.rect().bottomLeft())
        picker.move(pos)
        picker.show()

    def _set_emoji_button(self, emoji: str):
        self.btn_emoji_picker.setText(emoji)

    def _on_save(self):
        db = LocalDB()
        db.set_setting("font_family", self.combo_font.currentText())
        db.set_setting("font_size", str(self.spin_size.value()))
        db.set_setting("btn_text", self.input_btn_text.text() or "Отправить")
        db.set_setting("placeholder", self.input_placeholder.text() or "Введите сообщение...")
        db.set_setting("emoji_button", self.btn_emoji_picker.text())

        theme_str = "custom" if "Пользовательская" in self.combo_theme.currentText() else "base"
        db.set_setting("theme", theme_str)

        self.settings_changed.emit()
        self.close()

    def _on_add_account(self):
        self.add_account_requested.emit()
        self.close()

    def _on_logout(self):
        reply = QMessageBox.question(self, "Выход", f"Выйти из аккаунта {self.user.login}?")
        if reply == QMessageBox.Yes:
            self.logout_requested.emit()
            self.close()

    def _on_account_clicked(self, item):
        fp16 = item.data(Qt.UserRole)
        if fp16 and fp16 != self.user.fp16:
            self.switch_requested.emit(fp16)
            self.close()