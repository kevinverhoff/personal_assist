import os
import sqlite3


_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  gmail_message_id TEXT PRIMARY KEY,
  thread_id TEXT,
  sender_email TEXT,
  sender_name TEXT,
  subject TEXT,
  received_at TEXT,
  snippet TEXT,
  message_type TEXT,
  importance TEXT,
  action_required INTEGER,
  keep_in_inbox INTEGER,
  digest_worthy INTEGER,
  confidence REAL,
  reasoning TEXT,
  person_org_signal TEXT,
  matched_person_id TEXT,
  matched_org_ids TEXT,
  processed_at TEXT,
  archived INTEGER DEFAULT 0,
  archived_at TEXT,
  run_at TEXT,
  label_applied TEXT
);

CREATE TABLE IF NOT EXISTS sync_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  last_history_id TEXT,
  last_run_at TEXT
);

CREATE TABLE IF NOT EXISTS run_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at TEXT,
  messages_processed INTEGER,
  status TEXT,
  errors TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  gmail_message_id TEXT,
  original_classification TEXT,
  corrected_fields TEXT,
  note TEXT,
  corrected_at TEXT
);
"""

_MESSAGE_COLUMNS = [
    "gmail_message_id", "thread_id", "sender_email", "sender_name", "subject",
    "received_at", "snippet", "message_type", "importance", "action_required",
    "keep_in_inbox", "digest_worthy", "confidence", "reasoning",
    "person_org_signal", "matched_person_id", "matched_org_ids", "processed_at",
    "run_at", "label_applied",
]


_MIGRATION_COLUMNS = {
    "archived": "INTEGER DEFAULT 0",
    "archived_at": "TEXT",
    "run_at": "TEXT",
    "label_applied": "TEXT",
}


def _migrate_messages_table(conn: sqlite3.Connection) -> None:
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
    for column, column_type in _MIGRATION_COLUMNS.items():
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {column} {column_type}")
    conn.commit()


def init_db(db_path: str) -> sqlite3.Connection:
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    _migrate_messages_table(conn)
    return conn


def upsert_message(conn: sqlite3.Connection, message: dict) -> None:
    placeholders = ", ".join("?" for _ in _MESSAGE_COLUMNS)
    columns = ", ".join(_MESSAGE_COLUMNS)
    update_clause = ", ".join(f"{col} = excluded.{col}" for col in _MESSAGE_COLUMNS if col != "gmail_message_id")
    conn.execute(
        f"INSERT INTO messages ({columns}) VALUES ({placeholders}) "
        f"ON CONFLICT(gmail_message_id) DO UPDATE SET {update_clause}",
        [message.get(col) for col in _MESSAGE_COLUMNS],
    )
    conn.commit()


def get_sync_state(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT last_history_id, last_run_at FROM sync_state WHERE id = 1").fetchone()
    return dict(row) if row else None


def set_sync_state(conn: sqlite3.Connection, last_history_id: str, last_run_at: str) -> None:
    conn.execute(
        "INSERT INTO sync_state (id, last_history_id, last_run_at) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET last_history_id = excluded.last_history_id, "
        "last_run_at = excluded.last_run_at",
        (last_history_id, last_run_at),
    )
    conn.commit()


def insert_run_log(conn: sqlite3.Connection, run_at: str, messages_processed: int, status: str, errors: str | None) -> None:
    conn.execute(
        "INSERT INTO run_log (run_at, messages_processed, status, errors) VALUES (?, ?, ?, ?)",
        (run_at, messages_processed, status, errors),
    )
    conn.commit()


def insert_feedback(conn: sqlite3.Connection, gmail_message_id: str, original_classification: str,
                     corrected_fields: str, note: str, corrected_at: str) -> None:
    conn.execute(
        "INSERT INTO feedback (gmail_message_id, original_classification, corrected_fields, note, corrected_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (gmail_message_id, original_classification, corrected_fields, note, corrected_at),
    )
    conn.commit()


def mark_archived(conn: sqlite3.Connection, gmail_message_id: str, archived_at: str) -> None:
    conn.execute(
        "UPDATE messages SET archived = 1, archived_at = ? WHERE gmail_message_id = ?",
        (archived_at, gmail_message_id),
    )
    conn.commit()


def get_messages_in_window(conn: sqlite3.Connection, start_iso: str, end_iso: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM messages WHERE received_at >= ? AND received_at <= ? ORDER BY received_at",
        (start_iso, end_iso),
    ).fetchall()
    return [dict(row) for row in rows]


def get_latest_run_at(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT run_at FROM run_log WHERE status = 'ok' ORDER BY run_at DESC LIMIT 1"
    ).fetchone()
    return row["run_at"] if row else None


def get_messages_for_run(conn: sqlite3.Connection, run_at: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM messages WHERE run_at = ? ORDER BY received_at", (run_at,)
    ).fetchall()
    return [dict(row) for row in rows]


def get_recent_messages(conn: sqlite3.Connection, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM messages ORDER BY received_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(row) for row in rows]
