"""Точка входа Pygram."""

import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from config import load_config, ensure_config, get_app_dir
from src.utils.logger import setup_logging
from src.ui.theme import load_theme
from src.ui.login_view import LoginView
from src.ui.main_window import MainWindow
from src.ui.session_view import SessionView


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Pygram")
    app.setApplicationDisplayName("Pygram")

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

    # 3. Применяем БАЗОВУЮ тему (она всегда темная)
    load_theme(app, "base")

    # 4. Проверка папки шары
    shared_path = Path(config.shared_folder)
    if not shared_path.is_dir():
        try:
            shared_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(None, "Ошибка", f"Не удалось создать папку шары:\n{shared_path}")
            sys.exit(1)

    # 5. Запуск UI
    app_state = {"current_window": None}

    def on_logged_in(user):
        if app_state["current_window"]:
            app_state["current_window"].close()
        main_win = MainWindow(user)
        main_win.show()
        app_state["current_window"] = main_win

    from src.core.user import list_saved_sessions
    sessions = list_saved_sessions()

    if sessions:
        last_session = sessions[0]
        window = SessionView(last_session, config.shared_folder)
        window.logged_in.connect(on_logged_in)

        def show_login():
            window.close()
            login_win = LoginView()
            login_win.logged_in.connect(on_logged_in)
            login_win.show()
            app_state["current_window"] = login_win

        window.switch_account.connect(show_login)
    else:
        window = LoginView()
        window.logged_in.connect(on_logged_in)

    window.show()
    app_state["current_window"] = window

    sys.exit(app.exec())


if __name__ == "__main__":
    main()