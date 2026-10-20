"""Уведомления Windows для Pygram."""

from loguru import logger

try:
    from plyer import notification
    PLYER_AVAILABLE = True
except ImportError:
    PLYER_AVAILABLE = False
    logger.warning("plyer не установлен, уведомления отключены")


def show_notification(title: str, message: str, timeout: int = 5):
    """Показывает системное уведомление Windows.

    Args:
        title: Заголовок уведомления.
        message: Текст уведомления.
        timeout: Время показа в секундах.
    """
    if not PLYER_AVAILABLE:
        return

    try:
        notification.notify(
            title=title,
            message=message,
            app_name="Pygram",
            timeout=timeout,
        )
    except Exception as e:
        logger.error(f"Ошибка показа уведомления: {e}")
