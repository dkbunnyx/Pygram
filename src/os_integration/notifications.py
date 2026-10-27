"""Уведомления Windows для Pygram."""

from loguru import logger

try:
    from plyer import notification
    PLYER_AVAILABLE = True
except ImportError as e:
    PLYER_AVAILABLE = False
    logger.error(f"plyer не установлен: {e}")


def show_notification(title: str, message: str, timeout: int = 5):
    if not PLYER_AVAILABLE:
        return

    try:
        notification.notify(
            title=title,
            message=message,
            app_name="Pygram",  # <--- ВОТ ОНО, НАЗВАНИЕ ПРИЛОЖЕНИЯ
            app_icon=None,      # Сюда можно потом закинуть путь к .ico
            timeout=timeout,
        )
    except Exception as e:
        logger.error(f"Ошибка показа уведомления: {e}")