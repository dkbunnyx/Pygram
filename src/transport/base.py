"""Абстрактный базовый класс транспорта для Pygram.

Определяет интерфейс, который должны реализовать все транспорты
(файловый, HTTP, WebSocket и т.д.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable


class Transport(ABC):
    """Базовый интерфейс для чтения/записи данных.

    Все пути — относительные (относительно корня шары/сервера).
    """

    @abstractmethod
    def put(self, path: str, data: bytes) -> None:
        """Атомарно записывает данные по пути.

        Args:
            path: Относительный путь к файлу.
            data: Содержимое файла.
        """
        pass

    @abstractmethod
    def get(self, path: str) -> bytes:
        """Читает данные по пути.

        Raises:
            FileNotFoundError: если файла нет.
        """
        pass

    @abstractmethod
    def list(self, path: str) -> list[str]:
        """Возвращает список файлов в директории.

        Args:
            path: Относительный путь к директории.

        Returns:
            Список имён файлов (без полных путей).
        """
        pass

    @abstractmethod
    def delete(self, path: str) -> None:
        """Удаляет файл.

        Raises:
            FileNotFoundError: если файла нет.
        """
        pass

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Проверяет, существует ли файл."""
        pass

    @abstractmethod
    def watch(self, path: str, callback: Callable[[str], None]) -> None:
        """Запускает отслеживание изменений в директории.

        Args:
            path: Директория для слежки.
            callback: Функция, которая вызывается при изменении файла.
                      Принимает относительный путь изменённого файла.
        """
        pass