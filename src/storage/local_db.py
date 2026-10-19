"""Локальная база данных Pygram (SQLite).

Хранит кэш расшифрованных сообщений, черновики и локальные настройки.
База лежит в %USERPROFILE%\\.pygram\\pygram.db
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from loguru import logger

from src.os_integration.win import get_local_dir

DB_VERSION = 1


class LocalDB:
    def __init__(self, db_path: Path | None = None):
        if db_path is None:
            db_path = get_local_dir() / "pygram.db"

        self.path = db_path
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Доступ к колонкам по имени
        self._init_schema()

    def _init_schema(self):
        """Создаёт таблицы, если их нет."""
        cursor = self.conn.cursor()

        # 1. Таблица сообщений (кэш)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                msg_id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                sender_fp16 TEXT NOT NULL,
                text TEXT NOT NULL,
                ts INTEGER NOT NULL,
                is_read INTEGER DEFAULT 0
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_ts ON messages(chat_id, ts)")

        # 2. Таблица черновиков
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS drafts (
                chat_id TEXT PRIMARY KEY,
                text TEXT NOT NULL
            )
        """)

        # 3. Локальные настройки (ключ-значение)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        cursor.execute(f"PRAGMA user_version = {DB_VERSION}")
        self.conn.commit()
        logger.info(f"БД инициализирована: {self.path}")

    def close(self):
        self.conn.close()

    # ========================================================================
    # Сообщения
    # ========================================================================

    def save_message(self, msg_id: str, chat_id: str, sender_fp16: str, text: str, ts: int):
        """Сохраняет расшифрованное сообщение в кэш."""
        self.conn.execute(
            "INSERT OR REPLACE INTO messages (msg_id, chat_id, sender_fp16, text, ts) VALUES (?, ?, ?, ?, ?)",
            (msg_id, chat_id, sender_fp16, text, ts)
        )
        self.conn.commit()

    def get_messages(self, chat_id: str) -> list[dict]:
        """Возвращает все сообщения чата, отсортированные по времени."""
        cursor = self.conn.execute(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY ts ASC",
            (chat_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def mark_read(self, chat_id: str):
        """Помечает все сообщения чата как прочитанные."""
        self.conn.execute("UPDATE messages SET is_read = 1 WHERE chat_id = ?", (chat_id,))
        self.conn.commit()

    # ========================================================================
    # Черновики
    # ========================================================================

    def save_draft(self, chat_id: str, text: str):
        """Сохраняет черновик. Если text пустой — удаляет черновик."""
        if not text.strip():
            self.conn.execute("DELETE FROM drafts WHERE chat_id = ?", (chat_id,))
        else:
            self.conn.execute(
                "INSERT OR REPLACE INTO drafts (chat_id, text) VALUES (?, ?)",
                (chat_id, text)
            )
        self.conn.commit()

    def get_draft(self, chat_id: str) -> str:
        """Возвращает текст черновика или пустую строку."""
        cursor = self.conn.execute("SELECT text FROM drafts WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        return row["text"] if row else ""

    # ========================================================================
    # Настройки
    # ========================================================================

    def set_setting(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        self.conn.commit()

    def get_setting(self, key: str, default: str = "") -> str:
        cursor = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default