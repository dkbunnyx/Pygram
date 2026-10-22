"""Делегат для отрисовки сообщений в QListView (Стиль Telegram)."""

from pathlib import Path
from PySide6.QtWidgets import QStyledItemDelegate
from PySide6.QtCore import Qt, QRect, QSize, QModelIndex, QPoint
from PySide6.QtGui import (
    QPainter, QPixmap, QColor, QFont, QTextDocument,
    QAbstractTextDocumentLayout, QPalette, QFontMetrics
)
from datetime import datetime


class MessageDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.font_size = 14
        self.my_msg_bg = "#4a90e2"
        self.other_msg_bg = "#e2a04a"
        self.show_header = True
        self.profile_dir = None
        self.db = None
        self.chat_files_dir = None

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

        # 1. Шапка (Ник + Аватарка) - ТОЛЬКО ДЛЯ ЧУЖИХ В ГРУППАХ
        header_height = 0
        if self.show_header and not is_me:
            header_height = 25
            avatar_path = self.profile_dir / f"{sender_fp16}.png" if self.profile_dir else None

            painter.setPen(QColor("#cdd6f4"))
            font = QFont("Segoe UI", 9, QFont.Bold)
            painter.setFont(font)

            name_text = self.db.get_login_by_fp16(sender_fp16) if self.db else sender_fp16[:8]

            if avatar_path and avatar_path.exists():
                pix = QPixmap(str(avatar_path)).scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                painter.drawPixmap(rect.left() + 10, rect.top() + 2, pix)
                text_rect = QRect(rect.left() + 35, rect.top(), 200, 20)
            else:
                text_rect = QRect(rect.left() + 10, rect.top(), 200, 20)

            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, name_text)

        # 2. Обработка текста (Проверка на файл)
        display_text = raw_text
        image_pixmap = None

        if raw_text.startswith("[FILE]") and raw_text.endswith("[/FILE]"):
            inner = raw_text[6:-7]
            if "|" in inner:
                stored_name, original_name = inner.split("|", 1)
            else:
                stored_name = original_name = inner

            ext = stored_name.lower().split('.')[-1]
            if ext in ('png', 'jpg', 'jpeg', 'gif', 'bmp') and self.chat_files_dir:
                file_path = self.chat_files_dir / stored_name
                if file_path.exists():
                    image_pixmap = QPixmap(str(file_path))
                    if image_pixmap.width() > 250:
                        image_pixmap = image_pixmap.scaledToWidth(250, Qt.SmoothTransformation)
                    display_text = ""
                else:
                    display_text = f"🖼 {original_name} (не найдено)"
            else:
                display_text = f"📥 {original_name}"

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
            checkmark = " ✓✓" if msg_id in read_by_other else " ✓"
            time_str += checkmark

        time_font = QFont("Segoe UI", 8)
        fm_time = QFontMetrics(time_font)
        time_width = fm_time.horizontalAdvance(time_str)

        reactions_str = ""
        reactions_width = 0
        if reactions:
            from collections import Counter
            counts = Counter(reactions.values())
            reactions_str = " ".join([f"{emoji}{count}" for emoji, count in counts.items()])
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

        bubble_y = rect.top() + header_height
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
            painter.translate(-bubble_rect.topLeft().x() - padding_left, -bubble_rect.topLeft().y() - 5)

        # 5. Время и галочки
        painter.setPen(QColor("#ffffff"))
        painter.setFont(time_font)

        time_x = bubble_rect.right() - time_width - padding_right
        time_y = bubble_rect.bottom() - 18

        painter.drawText(QRect(time_x, time_y, time_width, 15), Qt.AlignRight | Qt.AlignVCenter, time_str)

        # 6. Реакции
        if reactions_str:
            painter.setFont(QFont("Segoe UI", 9))
            react_x = time_x - reactions_width - 8
            painter.drawText(QRect(react_x, time_y, reactions_width, 15), Qt.AlignRight | Qt.AlignVCenter, reactions_str)

        painter.restore()

    def sizeHint(self, option, index):
        msg_data = index.data(Qt.UserRole)
        if not msg_data:
            return QSize(0, 0)

        raw_text = msg_data["text"]

        img_height = 0
        if raw_text.startswith("[FILE]") and raw_text.endswith("[/FILE]"):
            inner = raw_text[6:-7]
            stored_name = inner.split("|")[0] if "|" in inner else inner
            ext = stored_name.lower().split('.')[-1]
            if ext in ('png', 'jpg', 'jpeg', 'gif', 'bmp') and self.chat_files_dir:
                file_path = self.chat_files_dir / stored_name
                if file_path.exists():
                    pix = QPixmap(str(file_path))
                    if pix.width() > 250:
                        img_height = int(pix.height() * (250 / pix.width()))
                    else:
                        img_height = pix.height()

        if img_height > 0:
            height = img_height + 25
        else:
            doc = QTextDocument()
            doc.setDefaultFont(QFont("Segoe UI", self.font_size))
            doc.setHtml(raw_text)
            doc.setTextWidth(400)
            height = doc.size().height() + 25

        header_height = 25 if self.show_header and not msg_data.get("is_me", False) else 0
        height += header_height + 10
        return QSize(option.rect.width(), int(height))