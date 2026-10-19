"""Главное окно (пока заглушка)."""

from PySide6.QtWidgets import QMainWindow, QLabel, QVBoxLayout, QWidget
from PySide6.QtCore import Qt


class MainWindow(QMainWindow):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.setWindowTitle(f"Pygram - {user.login} ({user.role})")
        self.setFixedSize(600, 400)

        central = QWidget()
        layout = QVBoxLayout(central)

        label = QLabel(
            f"Успешный вход!\n\nЛогин: {self.user.login}\nFingerprint: {self.user.fp16}\nРоль: {self.user.role}")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 18px;")

        layout.addWidget(label)
        self.setCentralWidget(central)