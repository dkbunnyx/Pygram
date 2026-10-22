# """Виджет одного сообщения."""
#
# from PySide6.QtWidgets import (
#     QWidget, QVBoxLayout, QHBoxLayout, QLabel
# )
# from PySide6.QtCore import Qt, Signal
# from PySide6.QtGui import QPixmap, QMouseEvent
#
#
# class MessageWidget(QWidget):
#     """Одно сообщение в чате."""
#
#     clicked = Signal(str)
#     double_clicked = Signal(str)
#
#     def __init__(self, msg_id: str, sender_name: str, text_html: str,
#                  time_str: str, is_me: bool, avatar_path: str = None,
#                  reactions_html: str = "", font_size: int = 14,
#                  is_image: bool = False, file_path: str = None,
#                  bg_color: str = "#4a90e2", show_header: bool = True, parent=None):
#         super().__init__(parent)
#         self.msg_id = msg_id
#         self.is_me = is_me
#         self.is_image = is_image
#         self.file_path = file_path
#         self.bg_color = bg_color
#         self.show_header = show_header
#         self.is_selected = False
#         self._setup_ui(sender_name, text_html, time_str, avatar_path, reactions_html, font_size)
#
#     def _setup_ui(self, sender_name, text_html, time_str, avatar_path, reactions_html, font_size):
#         layout = QVBoxLayout(self)
#         layout.setContentsMargins(5, 2, 5, 2)
#         layout.setSpacing(2)
#
#         # Заголовок: аватарка + ник (только если show_header=True)
#         if self.show_header:
#             header = QHBoxLayout()
#             header.setSpacing(5)
#
#             if self.is_me:
#                 header.addStretch() # Прижимаем вправо для своих
#
#             if avatar_path:
#                 avatar_label = QLabel()
#                 pixmap = QPixmap(avatar_path)
#                 avatar_label.setPixmap(pixmap.scaled(20, 20, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
#                 avatar_label.setFixedSize(20, 20)
#                 avatar_label.setAttribute(Qt.WA_TransparentForMouseEvents)
#                 header.addWidget(avatar_label)
#
#             name_label = QLabel(sender_name)
#             name_label.setStyleSheet("font-weight: bold; font-size: 9pt;")
#             name_label.setAttribute(Qt.WA_TransparentForMouseEvents)
#             header.addWidget(name_label)
#
#             if not self.is_me:
#                 header.addStretch() # Прижимаем влево для чужих
#
#             layout.addLayout(header)
#
#         # Текст сообщения (баббл)
#         self.text_label = QLabel()
#         self.text_label.setTextFormat(Qt.RichText)
#         self.text_label.setText(text_html)
#         self.text_label.setWordWrap(True)
#         self.text_label.setCursor(Qt.PointingHandCursor)
#         self.text_label.setAttribute(Qt.WA_TransparentForMouseEvents)
#
#         self._apply_bubble_style(font_size)
#
#         self.text_label.setMaximumWidth(600)
#
#         if self.is_me:
#             layout.addWidget(self.text_label, alignment=Qt.AlignRight)
#         else:
#             layout.addWidget(self.text_label, alignment=Qt.AlignLeft)
#
#         # Время + галочки + реакции
#         footer = QHBoxLayout()
#         footer.setSpacing(5)
#
#         time_label = QLabel(time_str)
#         time_label.setStyleSheet("font-size: 8pt; color: gray;")
#         time_label.setAttribute(Qt.WA_TransparentForMouseEvents)
#
#         if reactions_html:
#             reactions_label = QLabel()
#             reactions_label.setTextFormat(Qt.RichText)
#             reactions_label.setText(reactions_html)
#             reactions_label.setStyleSheet("font-size: 9pt;")
#             reactions_label.setAttribute(Qt.WA_TransparentForMouseEvents)
#
#             if self.is_me:
#                 footer.addStretch()
#                 footer.addWidget(time_label)
#                 footer.addWidget(reactions_label)
#             else:
#                 footer.addWidget(reactions_label)
#                 footer.addWidget(time_label)
#                 footer.addStretch()
#         else:
#             if self.is_me:
#                 footer.addStretch()
#                 footer.addWidget(time_label)
#             else:
#                 footer.addWidget(time_label)
#                 footer.addStretch()
#
#         layout.addLayout(footer)
#
#     def _apply_bubble_style(self, font_size=14):
#         """Применяет стиль бабла в зависимости от того, выбрано оно или нет."""
#         if self.is_selected:
#             border = "2px solid #f38ba8"
#         else:
#             border = "2px solid transparent"
#
#         self.text_label.setStyleSheet(f"""
#             QLabel {{
#                 background-color: {self.bg_color};
#                 border-radius: 8px;
#                 border: {border};
#                 padding: 8px;
#                 font-size: {font_size}pt;
#             }}
#         """)
#
#     def set_selected(self, selected: bool, font_size: int = 14):
#         """Включает/выключает режим выделения."""
#         self.is_selected = selected
#         self._apply_bubble_style(font_size)
#
#     def mousePressEvent(self, event: QMouseEvent):
#         if event.button() == Qt.LeftButton:
#             pos = event.position().toPoint()
#             if self.text_label.geometry().contains(pos):
#                 self.clicked.emit(self.msg_id)
#                 return
#         super().mousePressEvent(event)
#
#     def mouseDoubleClickEvent(self, event: QMouseEvent):
#         if event.button() == Qt.LeftButton:
#             pos = event.position().toPoint()
#             if self.text_label.geometry().contains(pos):
#                 self.double_clicked.emit(self.msg_id)
#                 return
#         super().mouseDoubleClickEvent(event)