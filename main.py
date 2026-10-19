"""Точка входа Pygram."""

import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from config import load_config, ensure_config, get_app_dir
from src.utils.logger import setup_logging
from src.ui.login_view import LoginView
from src.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)  # Сначала создаем приложение для диалогов

    # 1. Проверка .env
    env_path = get_app_dir() / ".env"
    if not env_path.exists():
        folder = QFileDialog.getExistingDirectory(None, "Выберите папку для шары Pygram")
        if not folder:
            sys.exit(0)
        ensure_config(folder)

    # 2. Загрузка конфига
    try:
        config = load_config()
        setup_logging(config.log_level)
    except Exception as e:
        QMessageBox.critical(None, "Ошибка", f"Ошибка конфигурации: {e}")
        sys.exit(1)

    # 3. Проверка папки шары
    shared_path = Path(config.shared_folder)
    if not shared_path.is_dir():
        reply = QMessageBox.question(
            None, "Папка не найдена",
            f"Папка шары не найдена:\n{shared_path}\n\nСоздать её?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply == QMessageBox.StandardButton.Yes:
            shared_path.mkdir(parents=True, exist_ok=True)
        else:
            sys.exit(0)

    # 4. Запуск UI
    app_state = {"login_window": None, "main_window": None}

    def on_logged_in(user):
        app_state["login_window"].close()
        main_win = MainWindow(user)
        main_win.show()
        app_state["main_window"] = main_win

    login_win = LoginView()
    login_win.logged_in.connect(on_logged_in)
    login_win.show()
    app_state["login_window"] = login_win

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
