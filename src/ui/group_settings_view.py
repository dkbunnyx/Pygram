"""Окно настроек группы."""

from pathlib import Path
import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QMessageBox, QListWidget, QListWidgetItem, QMenu
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from loguru import logger

from src.storage.local_db import get_db
from src.core.crypto import unwrap_key, aes_encrypt, to_base64, from_base64, aes_decrypt
from src.storage.shared_store import load_chat_keys, load_chat_meta_enc, save_chat_meta_enc
from src.core.chat_logic import (
    remove_group_member, toggle_group_admin, toggle_group_permission, can_edit_group_profile
)


class GroupSettingsView(QWidget):
    def __init__(self, shared_folder: str | Path, user, chat_id: str, parent=None):
        super().__init__(parent)
        self.shared_folder = shared_folder
        self.user = user
        self.chat_id = chat_id
        self.is_creator = False

        self.setWindowTitle("Настройки группы")
        self.resize(500, 500)

        self._load_meta()
        self._setup_ui()

    def _load_meta(self):
        self.meta = {}
        try:
            keys = load_chat_keys(self.shared_folder, self.chat_id)
            wrapped = keys.get("wrapped", {})
            if self.user.fp16 in wrapped:
                group_key = unwrap_key(wrapped, self.user.fp16, self.user.priv_pem)
                enc = load_chat_meta_enc(self.shared_folder, self.chat_id)
                data = json.loads(enc.decode("utf-8"))

                if "nonce" in data and "ciphertext" in data:
                    aad = f"chat_id={self.chat_id}|meta".encode("utf-8")
                    decrypted = aes_decrypt(group_key, from_base64(data["nonce"]), from_base64(data["ciphertext"]), aad=aad)
                    self.meta = json.loads(decrypted.decode("utf-8"))

                    creator = self.meta.get("creator_fp16", "")
                    if creator == self.user.fp16:
                        self.is_creator = True
        except Exception as e:
            logger.error(f"Ошибка загрузки метаданных группы: {e}")

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()

        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(80, 80)
        self.avatar_label.setCursor(Qt.PointingHandCursor)
        self.avatar_label.mousePressEvent = self._on_change_avatar

        avatar_path = Path(self.shared_folder) / ".profiles" / f"{self.chat_id}.png"
        if avatar_path.exists():
            pixmap = QPixmap(str(avatar_path))
            self.avatar_label.setPixmap(pixmap.scaled(80, 80, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        else:
            self.avatar_label.setText("👥")
            self.avatar_label.setStyleSheet("font-size: 40px; background-color: #2a2a2a; border-radius: 40px;")
            self.avatar_label.setAlignment(Qt.AlignCenter)

        header_layout.addWidget(self.avatar_label)

        self.label_name = QLabel(self.meta.get("name", "Группа"))
        self.label_name.setStyleSheet("font-size: 20px; font-weight: bold;")
        header_layout.addWidget(self.label_name)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        if self.is_creator:
            self.btn_change_avatar = QPushButton("Сменить аватарку группы")
            self.btn_change_avatar.clicked.connect(lambda: self._on_change_avatar(None))
            layout.addWidget(self.btn_change_avatar)

            rename_layout = QHBoxLayout()
            self.input_name = QLineEdit(self.meta.get("name", ""))
            rename_layout.addWidget(self.input_name)
            btn_rename = QPushButton("Переименовать")
            btn_rename.clicked.connect(self._on_rename)
            rename_layout.addWidget(btn_rename)
            layout.addLayout(rename_layout)

        layout.addWidget(QLabel("<b>Участники (ПКМ — действия):</b>"))

        self.list_widget = QListWidget()
        db = get_db()
        members = self.meta.get("members", [])
        admins = self.meta.get("admins", [])

        for m in members:
            login = db.get_login_by_fp16(m)
            role = " (Админ)" if m in admins else ""
            if m == self.user.fp16:
                role += " (Вы)"
            item = QListWidgetItem(f"{login}{role}")
            item.setData(Qt.UserRole, m)
            self.list_widget.addItem(item)

        self.list_widget.itemClicked.connect(self._on_member_clicked)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_member_context_menu)
        layout.addWidget(self.list_widget)

    def _on_member_clicked(self, item):
        fp16 = item.data(Qt.UserRole)
        if fp16:
            from src.ui.profile_view import ProfileView
            self.profile_window = ProfileView(self.shared_folder, self.user, target_fp16=fp16)
            self.profile_window.show()

    def _on_member_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        target_fp16 = item.data(Qt.UserRole)
        if not target_fp16 or target_fp16 == self.user.fp16:
            return

        menu = QMenu(self)

        if self.is_creator:
            # Назначить/снять админа
            if target_fp16 in self.meta.get("admins", []):
                action_admin = menu.addAction("Снять админа")
            else:
                action_admin = menu.addAction("Назначить админом")
            action_admin.triggered.connect(lambda: self._toggle_admin(target_fp16))

            # Права (только если админ)
            if target_fp16 in self.meta.get("admins", []):
                perms = self.meta.get("member_permissions", {}).get(target_fp16, {})
                can_edit = perms.get("can_edit_profile", False)
                can_remove = perms.get("can_remove_members", False)

                menu.addSeparator()
                action_edit = menu.addAction(f"{'✅' if can_edit else '❌'} Может менять профиль")
                action_edit.triggered.connect(lambda: self._toggle_perm(target_fp16, "can_edit_profile"))

                action_remove = menu.addAction(f"{'✅' if can_remove else '❌'} Может удалять участников")
                action_remove.triggered.connect(lambda: self._toggle_perm(target_fp16, "can_remove_members"))

        # Удалить из группы
        if self.is_creator or self.meta.get("member_permissions", {}).get(self.user.fp16, {}).get("can_remove_members", False):
            menu.addSeparator()
            action_delete = menu.addAction("Удалить из группы")
            action_delete.triggered.connect(lambda: self._remove_member(target_fp16))

        menu.exec(self.list_widget.mapToGlobal(pos))

    def _toggle_admin(self, target_fp16: str):
        try:
            toggle_group_admin(self.shared_folder, self.chat_id, target_fp16, self.user.fp16, self.user.priv_pem)
            self.close()
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", str(e))

    def _toggle_perm(self, target_fp16: str, perm: str):
        try:
            toggle_group_permission(self.shared_folder, self.chat_id, target_fp16, perm, self.user.fp16, self.user.priv_pem)
            self.close()
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", str(e))

    def _remove_member(self, target_fp16: str):
        reply = QMessageBox.question(self, "Удаление", "Удалить участника из группы?")
        if reply == QMessageBox.Yes:
            try:
                remove_group_member(self.shared_folder, self.chat_id, target_fp16, self.user.fp16, self.user.priv_pem)
                self.close()
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", str(e))

    def _on_change_avatar(self, event):
        if not (self.is_creator or can_edit_group_profile(self.shared_folder, self.chat_id, self.user.fp16, self.user.priv_pem)):
            QMessageBox.warning(self, "Ошибка", "У вас нет прав на изменение профиля группы.")
            return

        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите аватарку группы", "", "Images (*.png *.jpg *.jpeg)")
        if file_path:
            from PIL import Image, ImageDraw
            profile_dir = Path(self.shared_folder) / ".profiles"
            profile_dir.mkdir(parents=True, exist_ok=True)

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

            dest = profile_dir / f"{self.chat_id}.png"
            output.save(dest, "PNG")

            self.close()

    def _on_rename(self):
        if not (self.is_creator or can_edit_group_profile(self.shared_folder, self.chat_id, self.user.fp16, self.user.priv_pem)):
            return

        new_name = self.input_name.text().strip()
        if not new_name:
            return

        try:
            keys = load_chat_keys(self.shared_folder, self.chat_id)
            wrapped = keys.get("wrapped", {})
            if self.user.fp16 in wrapped:
                group_key = unwrap_key(wrapped, self.user.fp16, self.user.priv_pem)

                self.meta["name"] = new_name

                aad = f"chat_id={self.chat_id}|meta".encode("utf-8")
                nonce, ct = aes_encrypt(group_key, json.dumps(self.meta).encode("utf-8"), aad=aad)
                enc_blob = json.dumps({"nonce": to_base64(nonce), "ciphertext": to_base64(ct)})
                save_chat_meta_enc(self.shared_folder, self.chat_id, enc_blob.encode("utf-8"))

                QMessageBox.information(self, "Успех", "Группа переименована")
                self.close()
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", str(e))