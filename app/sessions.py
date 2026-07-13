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
        self._session_index: Dict[str, str] = {}
        self._memory: Dict[str, Dict[str, Any]] = {}
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
                contact_id TEXT,
                metadata TEXT
            )
            """
        )
        cur.execute("PRAGMA table_info(sessions)")
        session_cols = {row[1] for row in cur.fetchall()}
        if "contact_id" not in session_cols:
            cur.execute("ALTER TABLE sessions ADD COLUMN contact_id TEXT DEFAULT 'default'")

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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                user_id TEXT,
                contact_id TEXT,
                summary TEXT,
                timeline TEXT,
                facts TEXT,
                patterns TEXT,
                schema_version TEXT,
                working_memory TEXT,
                episodic_memory TEXT,
                semantic_memory TEXT,
                meta TEXT,
                updated_at TEXT,
                PRIMARY KEY (user_id, contact_id)
            )
            """
        )
        cur.execute("PRAGMA table_info(memories)")
        memory_cols = {row[1] for row in cur.fetchall()}
        if "schema_version" not in memory_cols:
            cur.execute("ALTER TABLE memories ADD COLUMN schema_version TEXT DEFAULT '1.0'")
        if "working_memory" not in memory_cols:
            cur.execute("ALTER TABLE memories ADD COLUMN working_memory TEXT DEFAULT '[]'")
        if "episodic_memory" not in memory_cols:
            cur.execute("ALTER TABLE memories ADD COLUMN episodic_memory TEXT DEFAULT '[]'")
        if "semantic_memory" not in memory_cols:
            cur.execute("ALTER TABLE memories ADD COLUMN semantic_memory TEXT DEFAULT '{}'")
        if "meta" not in memory_cols:
            cur.execute("ALTER TABLE memories ADD COLUMN meta TEXT DEFAULT '{}'")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_contact ON sessions(user_id, contact_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id, id)")
        conn.commit()
        conn.close()

    def _session_key(self, user_id: str, contact_id: str) -> str:
        return f"{user_id}::{contact_id}"

    def create_session(
        self,
        user_id: str,
        contact_id: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        sid = f"sess_{uuid.uuid4().hex[:8]}"
        merged_meta = dict(metadata or {})
        merged_meta.setdefault("contact_id", contact_id)
        data = {
            "id": sid,
            "user_id": user_id,
            "contact_id": contact_id,
            "metadata": merged_meta,
        }
        if self.db_path:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO sessions (id, user_id, contact_id, metadata) VALUES (?, ?, ?, ?)",
                (sid, user_id, contact_id, json.dumps(merged_meta)),
            )
            conn.commit()
            conn.close()
        else:
            self._in_memory[sid] = data
            self._session_index[self._session_key(user_id, contact_id)] = sid
        return sid

    def get_or_create_session(
        self,
        user_id: str,
        contact_id: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        if self.db_path:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT id FROM sessions WHERE user_id = ? AND contact_id = ? ORDER BY rowid DESC LIMIT 1",
                (user_id, contact_id),
            )
            row = cur.fetchone()
            conn.close()
            if row and row[0]:
                return row[0]
            return self.create_session(user_id, contact_id=contact_id, metadata=metadata)

        key = self._session_key(user_id, contact_id)
        sid = self._session_index.get(key)
        if sid:
            return sid
        return self.create_session(user_id, contact_id=contact_id, metadata=metadata)

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
            if limit and limit > 0:
                cur.execute(
                    "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                    (session_id, limit),
                )
            else:
                cur.execute(
                    "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id ASC",
                    (session_id,),
                )
            rows = cur.fetchall()
            conn.close()
            if not (limit and limit > 0):
                return [{"role": r[0], "content": r[1], "created_at": r[2]} for r in rows]
            return [{"role": r[0], "content": r[1], "created_at": r[2]} for r in reversed(rows)]
        else:
            sess = self._in_memory.get(session_id, {})
            msgs = sess.get("messages", [])
            if limit and limit > 0:
                return msgs[-limit:]
            return msgs[:]

    def count_messages(self, session_id: str) -> int:
        if self.db_path:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(1) FROM messages WHERE session_id = ?", (session_id,))
            row = cur.fetchone()
            conn.close()
            return int(row[0]) if row and row[0] is not None else 0

        sess = self._in_memory.get(session_id, {})
        msgs = sess.get("messages", [])
        return len(msgs)

    def get_memory(self, user_id: str, contact_id: str = "default") -> Dict[str, Any]:
        empty = {
            "summary": "",
            "timeline": [],
            "facts": [],
            "patterns": "",
            "schema_version": "1.0",
            "working_memory": [],
            "episodic_memory": [],
            "semantic_memory": {},
            "meta": {},
            "updated_at": None,
        }
        if self.db_path:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT summary, timeline, facts, patterns, schema_version, working_memory, episodic_memory, semantic_memory, meta, updated_at FROM memories WHERE user_id = ? AND contact_id = ?",
                (user_id, contact_id),
            )
            row = cur.fetchone()
            conn.close()
            if not row:
                return empty
            return {
                "summary": row[0] or "",
                "timeline": json.loads(row[1] or "[]"),
                "facts": json.loads(row[2] or "[]"),
                "patterns": row[3] or "",
                "schema_version": row[4] or "1.0",
                "working_memory": json.loads(row[5] or "[]"),
                "episodic_memory": json.loads(row[6] or "[]"),
                "semantic_memory": json.loads(row[7] or "{}"),
                "meta": json.loads(row[8] or "{}"),
                "updated_at": row[9],
            }

        return self._memory.get(self._session_key(user_id, contact_id), empty)

    def upsert_memory(self, user_id: str, contact_id: str, memory: Dict[str, Any]):
        now = datetime.utcnow().isoformat() + "Z"
        payload = {
            "summary": memory.get("summary", "") or "",
            "timeline": memory.get("timeline", []) or [],
            "facts": memory.get("facts", []) or [],
            "patterns": memory.get("patterns", "") or "",
            "schema_version": str(memory.get("schema_version", "1.0") or "1.0"),
            "working_memory": memory.get("working_memory", []) or [],
            "episodic_memory": memory.get("episodic_memory", []) or [],
            "semantic_memory": memory.get("semantic_memory", {}) or {},
            "meta": memory.get("meta", {}) or {},
            "updated_at": now,
        }
        if self.db_path:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO memories (user_id, contact_id, summary, timeline, facts, patterns, schema_version, working_memory, episodic_memory, semantic_memory, meta, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, contact_id)
                DO UPDATE SET
                    summary = excluded.summary,
                    timeline = excluded.timeline,
                    facts = excluded.facts,
                    patterns = excluded.patterns,
                    schema_version = excluded.schema_version,
                    working_memory = excluded.working_memory,
                    episodic_memory = excluded.episodic_memory,
                    semantic_memory = excluded.semantic_memory,
                    meta = excluded.meta,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    contact_id,
                    payload["summary"],
                    json.dumps(payload["timeline"], ensure_ascii=False),
                    json.dumps(payload["facts"], ensure_ascii=False),
                    payload["patterns"],
                    payload["schema_version"],
                    json.dumps(payload["working_memory"], ensure_ascii=False),
                    json.dumps(payload["episodic_memory"], ensure_ascii=False),
                    json.dumps(payload["semantic_memory"], ensure_ascii=False),
                    json.dumps(payload["meta"], ensure_ascii=False),
                    now,
                ),
            )
            conn.commit()
            conn.close()
        else:
            self._memory[self._session_key(user_id, contact_id)] = payload
