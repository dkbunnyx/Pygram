"""Окно профиля Pygram (с поддержкой нескольких фото)."""

from pathlib import Path
import json
import shutil
import uuid
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QFileDialog, QMessageBox, QMenu
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QIcon
from loguru import logger

from src.storage.local_db import get_db


class ProfileView(QWidget):
    """Окно профиля (свой или чужой)."""

    def __init__(self, shared_folder: str | Path, user, target_fp16: str = None, parent=None):
        super().__init__(parent)
        self.shared_folder = shared_folder
        self.user = user
        self.target_fp16 = target_fp16 or user.fp16
        self.is_own = (self.target_fp16 == user.fp16)

        self.setWindowTitle("Мой профиль" if self.is_own else "Профиль")
        self.resize(400, 550)

        self.profile_dir = Path(self.shared_folder) / ".profiles"
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        self._setup_ui()
        self._load_profile()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Верхняя панель с кнопкой меню (три точки)
        top_bar = QHBoxLayout()
        top_bar.addStretch()

        if self.is_own:
            self.btn_menu = QPushButton("⋮")
            self.btn_menu.setFixedSize(30, 30)
            self.btn_menu.setStyleSheet("font-size: 20px; font-weight: bold; background: transparent; border: none;")
            self.btn_menu.setCursor(Qt.PointingHandCursor)
            self.btn_menu.clicked.connect(self._show_profile_menu)
            top_bar.addWidget(self.btn_menu)

        layout.addLayout(top_bar)

        # Контейнер для аватарки (чтобы клик срабатывал)
        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(150, 150)
        self.avatar_label.setAlignment(Qt.AlignCenter)
        self.avatar_label.setCursor(Qt.PointingHandCursor)
        self.avatar_label.mousePressEvent = self._on_avatar_clicked
        layout.addWidget(self.avatar_label, alignment=Qt.AlignCenter)

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

    def _show_profile_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: #313148; color: white; } QMenu::item:selected { background-color: #4a90e2; }")

        avatar_path = self.profile_dir / f"{self.target_fp16}.png"
        has_avatar = avatar_path.exists()

        if not has_avatar:
            action_add = menu.addAction("Добавить фото")
            action_add.triggered.connect(self._on_add_photo)
        else:
            action_add = menu.addAction("Добавить фото")
            action_add.triggered.connect(self._on_add_photo)

            action_change = menu.addAction("Изменить главное фото")
            action_change.triggered.connect(self._on_change_main_photo)

            # НОВЫЙ ПУНКТ: Удалить текущее фото
            action_delete_current = menu.addAction("Удалить текущее фото")
            action_delete_current.triggered.connect(self._on_delete_current_photo)

            menu.addSeparator()

            action_delete_all = menu.addAction("Удалить все фото")
            action_delete_all.triggered.connect(self._on_delete_all_photos)

        menu.exec(self.btn_menu.mapToGlobal(self.btn_menu.rect().bottomLeft()))

    # ========================================================================
    # ЛОГИКА ФОТОГРАФИЙ
    # ========================================================================

    def _get_photos_list(self) -> list[str]:
        """Возвращает список имен файлов фотографий."""
        photos_json = self.profile_dir / f"{self.target_fp16}.photos.json"
        if photos_json.exists():
            try:
                return json.loads(photos_json.read_text(encoding="utf-8")).get("photos", [])
            except Exception:
                return []

        # Если JSON нет, но есть старая аватарка
        main_photo = self.profile_dir / f"{self.target_fp16}.png"
        if main_photo.exists():
            return [f"{self.target_fp16}.png"]
        return []

    def _save_photos_list(self, photos: list[str]):
        """Сохраняет список фото в JSON."""
        photos_json = self.profile_dir / f"{self.target_fp16}.photos.json"
        photos_json.write_text(json.dumps({"photos": photos}), encoding="utf-8")

    def _on_add_photo(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите фото", "", "Images (*.png *.jpg *.jpeg)")
        if not file_path:
            return

        try:
            photos = self._get_photos_list()

            ext = Path(file_path).suffix.lower()
            new_filename = f"{uuid.uuid4().hex}{ext}"
            dest_path = self.profile_dir / new_filename

            self._process_and_save_image(file_path, dest_path)

            # Делаем новое фото главным (копируем как <fp16>.png)
            main_path = self.profile_dir / f"{self.target_fp16}.png"
            shutil.copy2(dest_path, main_path)

            # Добавляем в начало списка (чтобы было первым)
            photos.insert(0, new_filename)
            self._save_photos_list(photos)

            self._load_profile()
            QMessageBox.information(self, "Успех", "Фото добавлено и установлено главным")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось добавить фото: {e}")

    def _on_change_main_photo(self):
        """Изменяет текущее главное фото (перезаписывает <fp16>.png)."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите новое главное фото", "", "Images (*.png *.jpg *.jpeg)")
        if not file_path:
            return

        try:
            main_path = self.profile_dir / f"{self.target_fp16}.png"
            self._process_and_save_image(file_path, main_path)
            self._load_profile()
            QMessageBox.information(self, "Успех", "Главное фото изменено")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось изменить фото: {e}")

    def _on_delete_current_photo(self):
        """Удаляет только текущее главное фото и ставит следующее из списка."""
        photos = self._get_photos_list()

        main_path = self.profile_dir / f"{self.target_fp16}.png"
        if main_path.exists():
            main_path.unlink() # Удаляем файл аватарки

        if not photos:
            self._load_profile()
            return

        # Находим текущее имя фото (которое было главным) и удаляем его из списка
        # Так как мы не храним точную привязку, просто берем первый элемент списка
        # (потому что при добавлении мы ставили новое фото в начало списка и делали главным)

        # Но если пользователь менял главное фото через "Изменить", привязка может сбиться.
        # В нашем случае: при "Добавить" - оно в начале списка.
        # При "Изменить" - перезаписывается главный файл, но список не меняется.

        # Чтобы все работало корректно, будем считать, что первое фото в списке - это и есть текущее.
        # (Так как мы добавляем новые в начало списка).

        if photos:
            # Удаляем первый файл из списка
            removed_photo = photos.pop(0)
            removed_path = self.profile_dir / removed_photo
            if removed_path.exists() and removed_path.name != f"{self.target_fp16}.png":
                removed_path.unlink()

            self._save_photos_list(photos)

            # Если есть следующее фото, делаем его главным
            if photos:
                next_photo = photos[0]
                next_path = self.profile_dir / next_photo
                if next_path.exists():
                    shutil.copy2(next_path, main_path)

        self._load_profile()
        QMessageBox.information(self, "Успех", "Текущее фото удалено")

    def _on_delete_all_photos(self):
        reply = QMessageBox.question(
            self, "Удаление", "Вы уверены, что хотите удалить ВСЕ фото?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            photos = self._get_photos_list()
            for p in photos:
                p_path = self.profile_dir / p
                if p_path.exists():
                    p_path.unlink()

            main_path = self.profile_dir / f"{self.target_fp16}.png"
            if main_path.exists():
                main_path.unlink()

            photos_json = self.profile_dir / f"{self.target_fp16}.photos.json"
            if photos_json.exists():
                photos_json.unlink()

            self._load_profile()
            QMessageBox.information(self, "Успех", "Все фото удалены")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось удалить: {e}")

    def _process_and_save_image(self, file_path: str, dest_path: Path):
        """Обрезает в круг и сохраняет."""
        from PIL import Image, ImageDraw
        img = Image.open(file_path).convert("RGBA")

        min_size = min(img.size)
        left = (img.width - min_size) / 2
        top = (img.height - min_size) / 2
        right = (img.width + min_size) / 2
        bottom = (img.height + min_size) / 2
        img = img.crop((left, top, right, bottom))
        img = img.resize((300, 300), Image.Resampling.LANCZOS)

        mask = Image.new("L", (300, 300), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, 300, 300), fill=255)

        output = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
        output.paste(img, (0, 0), mask=mask)
        output.save(dest_path, "PNG")

    def _on_avatar_clicked(self, event):
        """Открывает галерею фото при клике на аватарку."""
        photos = self._get_photos_list()
        if not photos:
            return

        from src.ui.photo_gallery_view import PhotoGalleryView
        self.gallery_window = PhotoGalleryView(self.shared_folder, self.target_fp16)
        self.gallery_window.show()

    # ========================================================================
    # ОСТАЛЬНОЕ
    # ========================================================================

    def _load_profile(self):
        avatar_path = self.profile_dir / f"{self.target_fp16}.png"
        if avatar_path.exists():
            pixmap = QPixmap(str(avatar_path))
            self.avatar_label.setPixmap(pixmap.scaled(150, 150, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        else:
            self.avatar_label.setText("👤")
            self.avatar_label.setStyleSheet("font-size: 80px;")

        bio_path = self.profile_dir / f"{self.target_fp16}.json"
        bio_text = ""
        if bio_path.exists():
            try:
                data = json.loads(bio_path.read_text(encoding="utf-8"))
                bio_text = data.get("bio", "")
            except Exception:
                pass

        db = get_db()
        if self.is_own:
            self.input_bio.setText(bio_text)
            self.label_name.setText(self.user.login)
        else:
            self.label_bio.setText(bio_text or "Пользователь ничего не рассказал о себе.")
            self.label_name.setText(db.get_login_by_fp16(self.target_fp16))

    def _on_save_bio(self):
        bio_text = self.input_bio.text().strip()
        bio_path = self.profile_dir / f"{self.target_fp16}.json"
        bio_path.write_text(json.dumps({"bio": bio_text}), encoding="utf-8")
        QMessageBox.information(self, "Успех", "Информация сохранена")