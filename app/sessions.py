import sqlite3
import json
import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime


class SessionManager:
    """Simple session manager with in-memory and optional SQLite persistence.

    Designed for prototype use; schema and implementation are intentionally
    simple to ease later migration to PostgreSQL.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self._in_memory: Dict[str, Dict[str, Any]] = {}
        if db_path:
            self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                metadata TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                created_at TEXT
            )
            """
        )
        conn.commit()
        conn.close()

    def create_session(self, user_id: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        sid = f"sess_{uuid.uuid4().hex[:8]}"
        data = {"id": sid, "user_id": user_id, "metadata": metadata or {}}
        if self.db_path:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("INSERT INTO sessions (id, user_id, metadata) VALUES (?, ?, ?)", (sid, user_id, json.dumps(metadata or {})))
            conn.commit()
            conn.close()
        else:
            self._in_memory[sid] = data
        return sid

    def append_message(self, session_id: str, role: str, text: str):
        now = datetime.utcnow().isoformat() + "Z"
        if self.db_path:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)", (session_id, role, text, now))
            conn.commit()
            conn.close()
        else:
            sess = self._in_memory.get(session_id)
            if not sess:
                return
            msgs = sess.setdefault("messages", [])
            msgs.append({"role": role, "content": text, "created_at": now})

    def get_context(self, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        if self.db_path:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?", (session_id, limit))
            rows = cur.fetchall()
            conn.close()
            return [{"role": r[0], "content": r[1], "created_at": r[2]} for r in reversed(rows)]
        else:
            sess = self._in_memory.get(session_id, {})
            msgs = sess.get("messages", [])
            return msgs[-limit:]
