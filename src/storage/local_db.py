"""Локальная база данных Pygram (SQLite)."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from loguru import logger

from src.os_integration.win import get_local_dir

DB_VERSION = 2


class LocalDB:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: Path | None = None):
        """Паттерн Singleton: всегда возвращает один и тот же экземпляр."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: Path | None = None):
        # Инициализируем только один раз
        if self._initialized:
            return

        if db_path is None:
            db_path = get_local_dir() / "pygram.db"

        self.path = db_path
        self._local = threading.local()

        conn = self._get_conn()
        self._init_schema()
        self._initialized = True

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(str(self.path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self):
        conn = self._get_conn()
        cursor = conn.cursor()

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

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS drafts (
                chat_id TEXT PRIMARY KEY,
                text TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users_map (
                fp16 TEXT PRIMARY KEY,
                login TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chats_cache (
                chat_id TEXT PRIMARY KEY,
                chat_type TEXT NOT NULL,
                title TEXT NOT NULL
            )
        """)

        cursor.execute(f"PRAGMA user_version = {DB_VERSION}")
        conn.commit()
        logger.info(f"БД инициализирована: {self.path}")

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    # ========================================================================
    # Сообщения
    # ========================================================================

    def save_message(self, msg_id: str, chat_id: str, sender_fp16: str, text: str, ts: int):
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO messages (msg_id, chat_id, sender_fp16, text, ts) VALUES (?, ?, ?, ?, ?)",
            (msg_id, chat_id, sender_fp16, text, ts)
        )
        conn.commit()

    def delete_message(self, msg_id: str):
        conn = self._get_conn()
        conn.execute("DELETE FROM messages WHERE msg_id = ?", (msg_id,))
        conn.commit()

    def get_messages(self, chat_id: str) -> list[dict]:
        conn = self._get_conn()
        cursor = conn.execute("SELECT * FROM messages WHERE chat_id = ? ORDER BY ts ASC", (chat_id,))
        return [dict(row) for row in cursor.fetchall()]

    def mark_read(self, chat_id: str):
        conn = self._get_conn()
        conn.execute("UPDATE messages SET is_read = 1 WHERE chat_id = ?", (chat_id,))
        conn.commit()

    # ========================================================================
    # Остальное
    # ========================================================================

    def save_draft(self, chat_id: str, text: str):
        conn = self._get_conn()
        if not text.strip():
            conn.execute("DELETE FROM drafts WHERE chat_id = ?", (chat_id,))
        else:
            conn.execute("INSERT OR REPLACE INTO drafts (chat_id, text) VALUES (?, ?)", (chat_id, text))
        conn.commit()

    def get_draft(self, chat_id: str) -> str:
        cursor = self._get_conn().execute("SELECT text FROM drafts WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        return row["text"] if row else ""

    def set_setting(self, key: str, value: str):
        conn = self._get_conn()
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

    def get_setting(self, key: str, default: str = "") -> str:
        cursor = self._get_conn().execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default

    def save_user_map(self, fp16: str, login: str):
        conn = self._get_conn()
        conn.execute("INSERT OR REPLACE INTO users_map (fp16, login) VALUES (?, ?)", (fp16, login))
        conn.commit()

    def get_login_by_fp16(self, fp16: str) -> str:
        cursor = self._get_conn().execute("SELECT login FROM users_map WHERE fp16 = ?", (fp16,))
        row = cursor.fetchone()
        return row["login"] if row else fp16[:8]

    def save_chat_cache(self, chat_id: str, chat_type: str, title: str):
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO chats_cache (chat_id, chat_type, title) VALUES (?, ?, ?)",
            (chat_id, chat_type, title)
        )
        conn.commit()

    def get_chat_cache(self, chat_id: str) -> dict | None:
        cursor = self._get_conn().execute(
            "SELECT chat_type, title FROM chats_cache WHERE chat_id = ?",
            (chat_id,)
        )
        row = cursor.fetchone()
        if row:
            return {"type": row["chat_type"], "title": row["title"]}
        return None
    def delete_chat_messages(self, chat_id: str):
        """Удаляет всю историю чата из локальной БД."""
        conn = self._get_conn()
        conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        conn.commit()