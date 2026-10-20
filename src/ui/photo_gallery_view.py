"""Окно галереи фотографий пользователя."""

from pathlib import Path
import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap


class PhotoGalleryView(QWidget):
    def __init__(self, shared_folder: str | Path, target_fp16: str, parent=None):
        super().__init__(parent)
        self.shared_folder = shared_folder
        self.target_fp16 = target_fp16
        self.profile_dir = Path(shared_folder) / ".profiles"

        self.photos = []
        self.current_index = 0

        self.setWindowTitle("Фотографии")
        self.resize(500, 600)
        self.setStyleSheet("background-color: #1a1a2e;")

        self._setup_ui()
        self._load_photos()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Контейнер для фото
        self.photo_label = QLabel()
        self.photo_label.setAlignment(Qt.AlignCenter)
        self.photo_label.setStyleSheet("background-color: #000; border-radius: 10px;")
        layout.addWidget(self.photo_label, stretch=1)

        # Кнопки управления (стрелочки)
        btn_layout = QHBoxLayout()

        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedSize(50, 50)
        self.btn_prev.setStyleSheet("font-size: 20px; background-color: #313148; color: white; border-radius: 25px;")
        self.btn_prev.clicked.connect(self._prev_photo)
        btn_layout.addWidget(self.btn_prev)

        self.lbl_counter = QLabel("1 / 1")
        self.lbl_counter.setAlignment(Qt.AlignCenter)
        self.lbl_counter.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        btn_layout.addWidget(self.lbl_counter)

        self.btn_next = QPushButton("▶")
        self.btn_next.setFixedSize(50, 50)
        self.btn_next.setStyleSheet("font-size: 20px; background-color: #313148; color: white; border-radius: 25px;")
        self.btn_next.clicked.connect(self._next_photo)
        btn_layout.addWidget(self.btn_next)

        layout.addLayout(btn_layout)

    def _load_photos(self):
        photos_json = self.profile_dir / f"{self.target_fp16}.photos.json"

        if photos_json.exists():
            try:
                data = json.loads(photos_json.read_text(encoding="utf-8"))
                self.photos = data.get("photos", [])
            except Exception:
                self.photos = []
        else:
            # Если JSON нет, проверяем старую аватарку
            main_photo = self.profile_dir / f"{self.target_fp16}.png"
            if main_photo.exists():
                self.photos = [f"{self.target_fp16}.png"]

        if not self.photos:
            self.lbl_counter.setText("Нет фото")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            return

        self.current_index = 0
        self._update_photo()

    def _update_photo(self):
        photo_name = self.photos[self.current_index]
        photo_path = self.profile_dir / photo_name

        if photo_path.exists():
            pixmap = QPixmap(str(photo_path))
            scaled_pixmap = pixmap.scaled(
                self.photo_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.photo_label.setPixmap(scaled_pixmap)

        self.lbl_counter.setText(f"{self.current_index + 1} / {len(self.photos)}")

    def _prev_photo(self):
        if len(self.photos) > 1:
            self.current_index = (self.current_index - 1) % len(self.photos)
            self._update_photo()

    def _next_photo(self):
        if len(self.photos) > 1:
            self.current_index = (self.current_index + 1) % len(self.photos)
            self._update_photo()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_photo()  # Обновляем размер фото при ресайзе окна