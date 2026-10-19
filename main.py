"""Точка входа Pygram."""

import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from config import load_config, ensure_config, get_app_dir
from src.utils.logger import setup_logging
from src.ui.theme import load_theme
from src.ui.login_view import LoginView
from src.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Pygram")
    app.setApplicationDisplayName("Pygram")

    # 1. Автоматически создаем .env, если его нет
    env_path = get_app_dir() / ".env"
    if not env_path.exists():
        ensure_config()  # Создаст с DEFAULT_SHARED_FOLDER

    # 2. Загружаем конфиг
    try:
        config = load_config()
        setup_logging(config.log_level)
    except Exception as e:
        QMessageBox.critical(None, "Ошибка", f"Ошибка конфигурации: {e}")
        sys.exit(1)

    # 3. Применяем тему
    load_theme(app, config.theme)

    # 4. Проверяем папку шары (без диалогов!)
    shared_path = Path(config.shared_folder)
    if not shared_path.is_dir():
        QMessageBox.critical(
            None, "Ошибка",
            f"Папка шары не найдена:\n{shared_path}\n\nПроверьте подключение к сети."
        )
        sys.exit(1)

    # 5. Запуск UI (с проверкой сессий)
    app_state = {"login_window": None, "main_window": None}

    def on_logged_in(user):
        # Закрываем и окно логина, и окно сессии, если они есть
        if app_state["login_window"]:
            app_state["login_window"].close()

        main_win = MainWindow(user)
        main_win.show()
        app_state["main_window"] = main_win

    # Проверяем, есть ли сохраненные сессии
    from src.core.user import list_saved_sessions
    from src.ui.session_view import SessionView

    sessions = list_saved_sessions()

    if sessions:
        # Берем последнюю сессию (самую свежую)
        last_session = sessions[-1]
        window = SessionView(last_session, config.shared_folder)
        window.logged_in.connect(on_logged_in)

        # Если нажали "Другой аккаунт" — показываем обычный LoginView
        def show_login():
            window.close()
            login_win = LoginView()
            login_win.logged_in.connect(on_logged_in)
            login_win.show()
            app_state["login_window"] = login_win

        window.switch_account.connect(show_login)
    else:
        # Сессий нет — показываем обычный вход
        window = LoginView()
        window.logged_in.connect(on_logged_in)

    window.show()
    app_state["login_window"] = window

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
