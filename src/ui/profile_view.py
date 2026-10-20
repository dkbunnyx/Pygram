"""Окно профиля Pygram."""

from pathlib import Path
import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from loguru import logger

from src.storage.local_db import LocalDB


class ProfileView(QWidget):
    """Окно профиля (свой или чужой)."""

    def __init__(self, shared_folder: str | Path, user, target_fp16: str = None, parent=None):
        super().__init__(parent)
        self.shared_folder = shared_folder
        self.user = user
        self.target_fp16 = target_fp16 or user.fp16
        self.is_own = (self.target_fp16 == user.fp16)

        self.setWindowTitle("Мой профиль" if self.is_own else "Профиль")
        self.resize(400, 500)

        self._setup_ui()
        self._load_profile()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Аватарка
        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(150, 150)
        self.avatar_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.avatar_label, alignment=Qt.AlignCenter)

        # Кнопка смены аватарки
        if self.is_own:
            self.btn_change_avatar = QPushButton("Сменить аватарку")
            self.btn_change_avatar.clicked.connect(self._on_change_avatar)
            layout.addWidget(self.btn_change_avatar)

        # Имя пользователя
        self.label_name = QLabel("Логин")
        self.label_name.setStyleSheet("font-size: 20px; font-weight: bold;")
        self.label_name.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label_name)

        # О себе
        layout.addWidget(QLabel("<b>О себе:</b>"))
        if self.is_own:
            self.input_bio = QLineEdit()
            self.input_bio.setPlaceholderText("Расскажите о себе...")
            self.input_bio.returnPressed.connect(self._on_save_bio)
            layout.addWidget(self.input_bio)

            self.btn_save_bio = QPushButton("Сохранить")
            self.btn_save_bio.clicked.connect(self._on_save_bio)
            layout.addWidget(self.btn_save_bio)
        else:
            self.label_bio = QLabel("")
            self.label_bio.setWordWrap(True)
            layout.addWidget(self.label_bio)

        layout.addStretch()

    def _get_profile_dir(self) -> Path:
        return Path(self.shared_folder) / ".profiles"

    def _load_profile(self):
        profile_dir = self._get_profile_dir()
        profile_dir.mkdir(parents=True, exist_ok=True)

        # Загружаем аватарку
        avatar_path = profile_dir / f"{self.target_fp16}.png"
        if avatar_path.exists():
            pixmap = QPixmap(str(avatar_path))
            # Отображаем 150x150, исходник 300x300 (качество хорошее)
            self.avatar_label.setPixmap(pixmap.scaled(150, 150, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        else:
            self.avatar_label.setText("👤")
            self.avatar_label.setStyleSheet("font-size: 80px;")

        # Загружаем био
        bio_path = profile_dir / f"{self.target_fp16}.json"
        bio_text = ""
        if bio_path.exists():
            try:
                data = json.loads(bio_path.read_text(encoding="utf-8"))
                bio_text = data.get("bio", "")
            except Exception:
                pass

        db = LocalDB()
        if self.is_own:
            self.input_bio.setText(bio_text)
            self.label_name.setText(self.user.login)
        else:
            self.label_bio.setText(bio_text or "Пользователь ничего не рассказал о себе.")
            self.label_name.setText(db.get_login_by_fp16(self.target_fp16))

    def _on_change_avatar(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите аватарку", "", "Images (*.png *.jpg *.jpeg)")
        if file_path:
            profile_dir = self._get_profile_dir()
            profile_dir.mkdir(parents=True, exist_ok=True)

            from PIL import Image, ImageDraw

            img = Image.open(file_path).convert("RGBA")

            # Обрезаем до квадрата
            min_size = min(img.size)
            left = (img.width - min_size) / 2
            top = (img.height - min_size) / 2
            right = (img.width + min_size) / 2
            bottom = (img.height + min_size) / 2
            img = img.crop((left, top, right, bottom))

            # Увеличиваем до 300x300 для качества
            img = img.resize((300, 300), Image.Resampling.LANCZOS)

            # Круглая маска
            mask = Image.new("L", (300, 300), 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((0, 0, 300, 300), fill=255)

            output = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
            output.paste(img, (0, 0), mask=mask)

            dest = profile_dir / f"{self.target_fp16}.png"
            output.save(dest, "PNG")

            self._load_profile()
            QMessageBox.information(self, "Успех", "Аватарка обновлена")

    def _on_save_bio(self):
        bio_text = self.input_bio.text().strip()
        profile_dir = self._get_profile_dir()
        profile_dir.mkdir(parents=True, exist_ok=True)

        bio_path = profile_dir / f"{self.target_fp16}.json"
        bio_path.write_text(json.dumps({"bio": bio_text}), encoding="utf-8")

        QMessageBox.information(self, "Успех", "Информация сохранена")