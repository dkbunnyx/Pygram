"""Точка входа Pygram."""

import sys
from PySide6.QtWidgets import QApplication

from config import load_config
from src.utils.logger import setup_logging
from src.ui.login_view import LoginView
from src.ui.main_window import MainWindow


def main():
    try:
        config = load_config()
        setup_logging(config.log_level)
    except Exception as e:
        print(f"Ошибка конфигурации: {e}")
        sys.exit(1)

    app = QApplication(sys.argv)

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
