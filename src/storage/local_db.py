"""Локальная база данных Pygram (SQLite)."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from loguru import logger

from src.os_integration.win import get_local_dir

DB_VERSION = 3


class LocalDB:
    _instance = None
    _lock = threading.Lock()


    def __init__(self, db_path: Path | None = None):
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
            conn.execute("PRAGMA synchronous=NORMAL")
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

        # НОВАЯ ТАБЛИЦА: Прочитанные сообщения
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS read_messages (
                chat_id TEXT NOT NULL,
                msg_id TEXT NOT NULL,
                PRIMARY KEY (chat_id, msg_id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_read_msg ON read_messages(chat_id)")

        cursor.execute(f"PRAGMA user_version = {DB_VERSION}")
        conn.commit()
        logger.info(f"БД инициализирована: {self.path}")

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

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

    def delete_chat_messages(self, chat_id: str):
        conn = self._get_conn()
        conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM read_messages WHERE chat_id = ?", (chat_id,))
        conn.commit()

    def get_messages(self, chat_id: str) -> list[dict]:
        conn = self._get_conn()
        cursor = conn.execute("SELECT * FROM messages WHERE chat_id = ? ORDER BY ts ASC", (chat_id,))
        return [dict(row) for row in cursor.fetchall()]

    def get_messages_paginated(self, chat_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY ts DESC LIMIT ? OFFSET ?",
            (chat_id, limit, offset)
        )
        return [dict(row) for row in reversed(cursor.fetchall())]

    def mark_read(self, chat_id: str):
        conn = self._get_conn()
        conn.execute("UPDATE messages SET is_read = 1 WHERE chat_id = ?", (chat_id,))
        conn.commit()

    def mark_messages_read(self, chat_id: str, msg_ids: list[str]):
        """Сохраняет прочитанные сообщения в БД."""
        if not msg_ids:
            return
        conn = self._get_conn()
        data = [(chat_id, mid) for mid in msg_ids]
        conn.executemany("INSERT OR IGNORE INTO read_messages (chat_id, msg_id) VALUES (?, ?)", data)
        conn.commit()

    def get_read_messages(self, chat_id: str) -> set[str]:
        """Возвращает множество прочитанных msg_id для чата."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT msg_id FROM read_messages WHERE chat_id = ?", (chat_id,))
        return {row["msg_id"] for row in cursor.fetchall()}

    def get_unread_count(self, chat_id: str, my_fp16: str) -> int:
        """Считает непрочитанные сообщения локально."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT msg_id, sender_fp16 FROM messages WHERE chat_id = ?",
            (chat_id,)
        )
        all_msgs = cursor.fetchall()
        read_msgs = self.get_read_messages(chat_id)

        count = 0
        for m in all_msgs:
            if m["sender_fp16"] != my_fp16 and m["msg_id"] not in read_msgs:
                count += 1
        return count

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
    def __new__(cls, db_path: Path | None = None):
        if db_path is not None:
            instance = super().__new__(cls)
            instance._initialized = False
            return instance

        # Production: Singleton
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance