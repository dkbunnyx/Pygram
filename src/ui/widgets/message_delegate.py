"""Делегат для отрисовки сообщений в QListView (Стиль Telegram)."""

import json
from pathlib import Path

from PySide6.QtWidgets import QStyledItemDelegate
from PySide6.QtCore import Qt, QRect, QSize, QModelIndex, QPoint, Signal
from PySide6.QtGui import (
    QPainter,
    QPixmap,
    QColor,
    QFont,
    QTextDocument,
    QAbstractTextDocumentLayout,
    QPalette,
    QFontMetrics,
)
from datetime import datetime


class MessageDelegate(QStyledItemDelegate):
    attachment_preview_requested = Signal(str, str, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.font_size = 14
        self.my_msg_bg = "#4a90e2"
        self.other_msg_bg = "#e2a04a"
        self.show_header = True
        self.profile_dir = None
        self.db = None
        self.chat_files_dir = None
        self.attachment_previews = {}
        self.attachment_preview_pending = set()
        self.attachment_preview_errors = set()

    def set_attachment_preview(self, msg_id: str, image_data: bytes):
        """Сохраняет расшифрованное превью в памяти."""
        pixmap = QPixmap()

        if not pixmap.loadFromData(image_data):
            self.attachment_preview_pending.discard(msg_id)
            self.attachment_preview_errors.add(msg_id)
            self.parent().viewport().update()
            return

        self.attachment_previews[msg_id] = pixmap
        self.attachment_preview_pending.discard(msg_id)
        self.attachment_preview_errors.discard(msg_id)

        if self.parent():
            self.parent().viewport().update()

    def set_attachment_preview_error(self, msg_id: str):
        """Отмечает, что превью не удалось загрузить."""
        self.attachment_preview_pending.discard(msg_id)
        self.attachment_preview_errors.add(msg_id)

        if self.parent():
            self.parent().viewport().update()

    def _get_date_header(self, index):
        """Возвращает дату, если перед сообщением нужен разделитель."""
        msg_data = index.data(Qt.UserRole)

        if not msg_data:
            return None

        current_date = datetime.fromtimestamp(msg_data["ts"] / 1000).date()

        # Первое сообщение всегда начинает новый раздел.
        if index.row() == 0:
            show_header = True
        else:
            previous_index = index.model().index(
                index.row() - 1,
                index.column(),
            )
            previous_data = previous_index.data(Qt.UserRole)

            if not previous_data:
                show_header = True
            else:
                previous_date = datetime.fromtimestamp(
                    previous_data["ts"] / 1000
                ).date()

                show_header = current_date != previous_date

        if not show_header:
            return None

        months = [
            "января",
            "февраля",
            "марта",
            "апреля",
            "мая",
            "июня",
            "июля",
            "августа",
            "сентября",
            "октября",
            "ноября",
            "декабря",
        ]

        date_text = f"{current_date.day} {months[current_date.month - 1]}"

        if current_date.year != datetime.now().year:
            date_text += f" {current_date.year}"

        return date_text

    def paint(self, painter: QPainter, option, index: QModelIndex):
        msg_data = index.data(Qt.UserRole)
        if not msg_data:
            return

        painter.save()

        msg_id = msg_data["msg_id"]
        sender_fp16 = msg_data["sender_fp16"]
        raw_text = msg_data["text"]
        ts = msg_data["ts"]
        is_me = msg_data.get("is_me", False)
        read_by_other = msg_data.get("read_by_other", [])
        reactions = msg_data.get("reactions", {})

        rect = option.rect
        bubble_color = self.my_msg_bg if is_me else self.other_msg_bg

        # Проверяем, нужно ли показать разделитель даты.
        date_header = self._get_date_header(index)
        date_header_height = 30 if date_header else 0

        if date_header:
            date_font = QFont("Segoe UI", 9, QFont.DemiBold)
            painter.setFont(date_font)

            date_metrics = QFontMetrics(date_font)
            date_width = date_metrics.horizontalAdvance(date_header) + 24

            date_rect = QRect(
                rect.center().x() - date_width // 2,
                rect.top() + 3,
                date_width,
                23,
            )

            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#313148"))
            painter.drawRoundedRect(date_rect, 10, 10)

            painter.setPen(QColor("#cdd6f4"))
            painter.drawText(
                date_rect,
                Qt.AlignCenter,
                date_header,
            )

        # 1. Шапка (Ник + Аватарка) - ТОЛЬКО ДЛЯ ЧУЖИХ В ГРУППАХ
        header_height = 0
        if self.show_header and not is_me:
            header_height = 25
            avatar_path = (
                self.profile_dir / f"{sender_fp16}.png" if self.profile_dir else None
            )

            painter.setPen(QColor("#cdd6f4"))
            font = QFont("Segoe UI", 9, QFont.Bold)
            painter.setFont(font)

            name_text = (
                self.db.get_login_by_fp16(sender_fp16) if self.db else sender_fp16[:8]
            )

            if avatar_path and avatar_path.exists():
                pix = QPixmap(str(avatar_path)).scaled(
                    20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                painter.drawPixmap(rect.left() + 10, rect.top() + 2, pix)
                text_rect = QRect(rect.left() + 35, rect.top(), 200, 20)
            else:
                text_rect = QRect(rect.left() + 10, rect.top(), 200, 20)

            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, name_text)

        # 2. Обработка зашифрованного вложения
        display_text = raw_text
        image_pixmap = None

        if raw_text.startswith("[FILE]") and raw_text.endswith("[/FILE]"):
            try:
                inner = raw_text[6:-7]
                attachment_data = json.loads(inner)

                stored_name = attachment_data.get("stored_name", "")
                original_name = attachment_data.get("original_name", "Файл")

                ext = Path(original_name).suffix.lower()
                image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}

                if ext in image_extensions:
                    image_pixmap = self.attachment_previews.get(msg_id)

                    if image_pixmap is None:
                        if msg_id not in self.attachment_preview_pending:
                            self.attachment_preview_pending.add(msg_id)
                            self.attachment_preview_requested.emit(
                                msg_id,
                                sender_fp16,
                                attachment_data,
                            )

                        if msg_id in self.attachment_preview_errors:
                            display_text = f"🖼 {original_name} (ошибка загрузки)"
                        else:
                            display_text = f"🖼 {original_name} (загрузка...)"
                    else:
                        display_text = ""
                        if image_pixmap.width() > 250:
                            image_pixmap = image_pixmap.scaledToWidth(
                                250,
                                Qt.SmoothTransformation,
                            )
                else:
                    display_text = f"📥 {original_name}"

            except (ValueError, TypeError, json.JSONDecodeError):
                display_text = "⚠ Некорректное вложение"

        # 3. Подготовка текста и времени
        doc = QTextDocument()
        doc.setDefaultFont(QFont("Segoe UI", self.font_size))

        if display_text:
            doc.setHtml(display_text)
            doc.setTextWidth(400)
            text_height = doc.size().height()
            text_width = int(doc.idealWidth())
        else:
            text_height = 0
            text_width = 0

        dt = datetime.fromtimestamp(ts / 1000)
        time_str = dt.strftime("%H:%M")

        if is_me:
            read_status = msg_data.get("read_status", "")
            if read_status == "all":
                checkmark = " ✓✓"
            else:
                checkmark = " ✓"
            time_str += checkmark

        time_font = QFont("Segoe UI", 8)
        fm_time = QFontMetrics(time_font)
        time_width = fm_time.horizontalAdvance(time_str)

        reactions_str = ""
        reactions_width = 0
        if reactions:
            from collections import Counter

            counts = Counter(reactions.values())
            reactions_str = " ".join(
                [f"{emoji}{count}" for emoji, count in counts.items()]
            )
            fm_react = QFontMetrics(QFont("Segoe UI", 9))
            reactions_width = fm_react.horizontalAdvance(reactions_str)

        # --- РАСЧЕТ ШИРИНЫ БАБЛА ---
        padding_left = 10
        padding_right = 8

        content_width = image_pixmap.width() if image_pixmap else text_width

        width_for_text = padding_left + content_width + padding_right
        bottom_row_width = time_width + 5
        if reactions_str:
            bottom_row_width += reactions_width + 8

        width_for_bottom = padding_left + bottom_row_width + padding_right

        bubble_width = max(width_for_text, width_for_bottom, 60)

        content_height = image_pixmap.height() if image_pixmap else int(text_height)
        bubble_height = content_height + 25

        bubble_y = rect.top() + date_header_height + header_height
        if is_me:
            bubble_x = rect.right() - bubble_width - 10
        else:
            bubble_x = rect.left() + 10

        bubble_rect = QRect(bubble_x, bubble_y, bubble_width, bubble_height)

        painter.setBrush(QColor(bubble_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(bubble_rect, 8, 8)

        # 4. Рисуем контент
        if image_pixmap:
            img_x = bubble_rect.left() + (bubble_width - image_pixmap.width()) // 2
            img_y = bubble_rect.top() + 5
            painter.drawPixmap(img_x, img_y, image_pixmap)
        elif display_text:
            painter.translate(bubble_rect.topLeft() + QPoint(padding_left, 5))
            ctx = QAbstractTextDocumentLayout.PaintContext()
            ctx.palette.setColor(QPalette.ColorRole.Text, QColor("#ffffff"))
            doc.documentLayout().draw(painter, ctx)
            painter.translate(
                -bubble_rect.topLeft().x() - padding_left,
                -bubble_rect.topLeft().y() - 5,
            )

        # 5. Время и галочки
        painter.setPen(QColor("#ffffff"))
        painter.setFont(time_font)

        time_x = bubble_rect.right() - time_width - padding_right
        time_y = bubble_rect.bottom() - 18

        painter.drawText(
            QRect(time_x, time_y, time_width, 15),
            Qt.AlignRight | Qt.AlignVCenter,
            time_str,
        )

        # 6. Реакции
        if reactions_str:
            painter.setFont(QFont("Segoe UI", 9))
            react_x = time_x - reactions_width - 8
            painter.drawText(
                QRect(react_x, time_y, reactions_width, 15),
                Qt.AlignRight | Qt.AlignVCenter,
                reactions_str,
            )

        painter.restore()

    def sizeHint(self, option, index):
        msg_data = index.data(Qt.UserRole)
        if not msg_data:
            return QSize(0, 0)

        raw_text = msg_data["text"]

        img_height = 0

        if raw_text.startswith("[FILE]") and raw_text.endswith("[/FILE]"):
            try:
                attachment_data = json.loads(raw_text[6:-7])
                original_name = attachment_data.get("original_name", "")
                ext = Path(original_name).suffix.lower()

                image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}

                if ext in image_extensions:
                    pixmap = self.attachment_previews.get(msg_data["msg_id"])

                    if pixmap:
                        if pixmap.width() > 250:
                            img_height = int(pixmap.height() * (250 / pixmap.width()))
                        else:
                            img_height = pixmap.height()

            except (ValueError, TypeError, json.JSONDecodeError):
                pass
        if img_height > 0:
            height = img_height + 25
        else:
            doc = QTextDocument()
            doc.setDefaultFont(QFont("Segoe UI", self.font_size))
            doc.setHtml(raw_text)
            doc.setTextWidth(400)
            height = doc.size().height() + 25

        header_height = (
            25 if self.show_header and not msg_data.get("is_me", False) else 0
        )
        date_header = self._get_date_header(index)
        date_header_height = 30 if date_header else 0

        height += header_height + date_header_height + 10
        return QSize(option.rect.width(), int(height))
