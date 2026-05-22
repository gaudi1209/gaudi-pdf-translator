"""
翻译缓存模块 - SQLite 实现
相同原文+模型不重复调用 LLM
"""
import hashlib
import sqlite3
import os
import threading
from typing import Optional


class TranslationCache:
    """SQLite 翻译缓存"""

    def __init__(self, cache_dir: str):
        self.cache_path = os.path.join(cache_dir, "translation_cache.db")
        self._local = threading.local()
        os.makedirs(cache_dir, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """获取线程安全的连接"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.cache_path)
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS translations (
                text_hash TEXT NOT NULL,
                model TEXT NOT NULL,
                original TEXT NOT NULL,
                translated TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (text_hash, model)
            )
        """)
        conn.commit()

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    def get(self, text: str, model: str) -> Optional[str]:
        """查询缓存，命中返回译文，未命中返回 None"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT translated FROM translations WHERE text_hash = ? AND model = ?",
            (self._hash(text), model)
        ).fetchone()
        return row[0] if row else None

    def put(self, text: str, translated: str, model: str):
        """写入缓存"""
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO translations (text_hash, model, original, translated) VALUES (?, ?, ?, ?)",
            (self._hash(text), model, text, translated)
        )
        conn.commit()

    def stats(self) -> dict:
        """缓存统计"""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM translations").fetchone()[0]
        return {"total_entries": total}

    def close(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
