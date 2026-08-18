import sqlite3

from email_agent import store


def test_init_db_creates_tables():
    conn = store.init_db(":memory:")
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    assert {"messages", "sync_state", "run_log", "feedback"} <= tables


def test_upsert_message_inserts_then_updates():
    conn = store.init_db(":memory:")
    message = {
        "gmail_message_id": "msg-1",
        "thread_id": "thread-1",
        "sender_email": "a@example.com",
        "sender_name": "A Sender",
        "subject": "Hello",
        "received_at": "2026-08-15T07:00:00Z",
        "snippet": "hi there",
        "message_type": "human",
        "importance": "high",
        "action_required": 1,
        "keep_in_inbox": 1,
        "digest_worthy": 0,
        "confidence": 0.9,
        "reasoning": "looks like a real person",
        "person_org_signal": None,
        "matched_person_id": None,
        "matched_org_ids": None,
        "processed_at": "2026-08-15T07:00:01Z",
    }
    store.upsert_message(conn, message)
    rows = conn.execute("SELECT subject FROM messages WHERE gmail_message_id = 'msg-1'").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Hello"

    message["subject"] = "Updated Subject"
    store.upsert_message(conn, message)
    rows = conn.execute("SELECT subject FROM messages WHERE gmail_message_id = 'msg-1'").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Updated Subject"


def test_sync_state_round_trip():
    conn = store.init_db(":memory:")
    assert store.get_sync_state(conn) is None
    store.set_sync_state(conn, last_history_id="12345", last_run_at="2026-08-15T07:00:00Z")
    state = store.get_sync_state(conn)
    assert state["last_history_id"] == "12345"
    store.set_sync_state(conn, last_history_id="67890", last_run_at="2026-08-15T08:00:00Z")
    state = store.get_sync_state(conn)
    assert state["last_history_id"] == "67890"


def test_insert_run_log():
    conn = store.init_db(":memory:")
    store.insert_run_log(conn, run_at="2026-08-15T07:00:00Z", messages_processed=5, status="ok", errors=None)
    rows = conn.execute("SELECT status, messages_processed FROM run_log").fetchall()
    assert [tuple(r) for r in rows] == [("ok", 5)]


def test_insert_and_fetch_feedback():
    conn = store.init_db(":memory:")
    store.insert_feedback(
        conn,
        gmail_message_id="msg-1",
        original_classification='{"importance": "low"}',
        corrected_fields='{"importance": "high"}',
        note="this was actually urgent",
        corrected_at="2026-08-15T09:00:00Z",
    )
    rows = conn.execute("SELECT gmail_message_id, note FROM feedback").fetchall()
    assert [tuple(r) for r in rows] == [("msg-1", "this was actually urgent")]


def test_get_messages_in_window_filters_by_date():
    conn = store.init_db(":memory:")
    for i, received_at in enumerate(["2026-08-14T07:00:00Z", "2026-08-15T07:00:00Z", "2026-08-16T07:00:00Z"]):
        store.upsert_message(conn, {
            "gmail_message_id": f"msg-{i}", "thread_id": "t", "sender_email": "a@example.com",
            "sender_name": "A", "subject": "s", "received_at": received_at, "snippet": "",
            "message_type": "newsletter", "importance": "low", "action_required": 0,
            "keep_in_inbox": 1, "digest_worthy": 1, "confidence": 0.9, "reasoning": "r",
            "person_org_signal": None, "matched_person_id": None, "matched_org_ids": None,
            "processed_at": received_at,
        })
    results = store.get_messages_in_window(conn, "2026-08-15T00:00:00Z", "2026-08-15T23:59:59Z")
    assert [m["gmail_message_id"] for m in results] == ["msg-1"]


def test_mark_archived_sets_flag_and_timestamp():
    conn = store.init_db(":memory:")
    store.upsert_message(conn, {
        "gmail_message_id": "msg-1", "thread_id": "t", "sender_email": "a@x.com",
        "sender_name": "A", "subject": "s", "received_at": "2026-08-17T07:00:00Z", "snippet": "",
        "message_type": "newsletter", "importance": "low", "action_required": 0,
        "keep_in_inbox": 0, "digest_worthy": 1, "confidence": 0.95, "reasoning": "r",
        "person_org_signal": None, "matched_person_id": None, "matched_org_ids": None,
        "processed_at": "2026-08-17T07:00:01Z",
    })
    store.mark_archived(conn, "msg-1", "2026-08-17T07:05:00Z")
    row = conn.execute("SELECT archived, archived_at FROM messages WHERE gmail_message_id = 'msg-1'").fetchone()
    assert row["archived"] == 1
    assert row["archived_at"] == "2026-08-17T07:05:00Z"


def test_mark_archived_stores_archive_summary():
    conn = store.init_db(":memory:")
    store.upsert_message(conn, {
        "gmail_message_id": "msg-1", "thread_id": "t", "sender_email": "a@x.com",
        "sender_name": "A", "subject": "s", "received_at": "2026-08-17T07:00:00Z", "snippet": "",
        "message_type": "newsletter", "importance": "low", "action_required": 0,
        "keep_in_inbox": 0, "digest_worthy": 1, "confidence": 0.95, "reasoning": "r",
        "person_org_signal": None, "matched_person_id": None, "matched_org_ids": None,
        "processed_at": "2026-08-17T07:00:01Z",
    })
    store.mark_archived(conn, "msg-1", "2026-08-17T07:05:00Z", archive_summary="Your package ships Tuesday.")
    row = conn.execute("SELECT archive_summary FROM messages WHERE gmail_message_id = 'msg-1'").fetchone()
    assert row["archive_summary"] == "Your package ships Tuesday."


def test_mark_archived_without_summary_defaults_to_none():
    conn = store.init_db(":memory:")
    store.upsert_message(conn, {
        "gmail_message_id": "msg-1", "thread_id": "t", "sender_email": "a@x.com",
        "sender_name": "A", "subject": "s", "received_at": "2026-08-17T07:00:00Z", "snippet": "",
        "message_type": "newsletter", "importance": "low", "action_required": 0,
        "keep_in_inbox": 0, "digest_worthy": 1, "confidence": 0.95, "reasoning": "r",
        "person_org_signal": None, "matched_person_id": None, "matched_org_ids": None,
        "processed_at": "2026-08-17T07:00:01Z",
    })
    store.mark_archived(conn, "msg-1", "2026-08-17T07:05:00Z")
    row = conn.execute("SELECT archive_summary FROM messages WHERE gmail_message_id = 'msg-1'").fetchone()
    assert row["archive_summary"] is None


def test_new_messages_default_to_not_archived():
    conn = store.init_db(":memory:")
    store.upsert_message(conn, {
        "gmail_message_id": "msg-1", "thread_id": "t", "sender_email": "a@x.com",
        "sender_name": "A", "subject": "s", "received_at": "2026-08-17T07:00:00Z", "snippet": "",
        "message_type": "human", "importance": "high", "action_required": 0,
        "keep_in_inbox": 1, "digest_worthy": 0, "confidence": 0.9, "reasoning": "r",
        "person_org_signal": None, "matched_person_id": None, "matched_org_ids": None,
        "processed_at": "2026-08-17T07:00:01Z",
    })
    row = conn.execute("SELECT archived FROM messages WHERE gmail_message_id = 'msg-1'").fetchone()
    assert row["archived"] == 0


def test_init_db_adds_new_columns_to_legacy_messages_table(tmp_path):
    # Reproduces the real scenario: an already-accumulated database file
    # created before archived/archived_at/run_at/label_applied existed.
    # Migration must add all of them without touching existing rows or
    # requiring a rebuild.
    db_path = str(tmp_path / "legacy.db")
    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.execute("""
        CREATE TABLE messages (
          gmail_message_id TEXT PRIMARY KEY,
          subject TEXT
        )
    """)
    legacy_conn.execute("INSERT INTO messages (gmail_message_id, subject) VALUES ('msg-1', 'old subject')")
    legacy_conn.commit()
    legacy_conn.close()

    conn = store.init_db(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
    assert {"archived", "archived_at", "run_at", "label_applied", "archive_summary"} <= columns
    row = conn.execute(
        "SELECT subject, archived, archived_at, run_at, label_applied, archive_summary "
        "FROM messages WHERE gmail_message_id = 'msg-1'"
    ).fetchone()
    assert row["subject"] == "old subject"
    assert row["archived"] == 0  # SQLite backfills ADD COLUMN ... DEFAULT 0 onto existing rows
    assert row["archived_at"] is None
    assert row["run_at"] is None
    assert row["label_applied"] is None
    assert row["archive_summary"] is None


def test_get_latest_run_at_returns_most_recent_ok_run():
    conn = store.init_db(":memory:")
    store.insert_run_log(conn, run_at="2026-08-17 14:20", messages_processed=14, status="ok", errors=None)
    store.insert_run_log(conn, run_at="2026-08-17 17:21", messages_processed=0, status="auth_error", errors="boom")
    store.insert_run_log(conn, run_at="2026-08-17 17:24", messages_processed=7, status="ok", errors=None)
    assert store.get_latest_run_at(conn) == "2026-08-17 17:24"


def test_get_latest_run_at_returns_none_when_no_successful_runs():
    conn = store.init_db(":memory:")
    store.insert_run_log(conn, run_at="2026-08-17 17:21", messages_processed=0, status="auth_error", errors="boom")
    assert store.get_latest_run_at(conn) is None


def test_get_messages_for_run_filters_by_run_at():
    conn = store.init_db(":memory:")
    for gmail_message_id, run_at in [("msg-1", "2026-08-17 14:20"), ("msg-2", "2026-08-17 17:24")]:
        store.upsert_message(conn, {
            "gmail_message_id": gmail_message_id, "thread_id": "t", "sender_email": "a@x.com",
            "sender_name": "A", "subject": gmail_message_id, "received_at": "2026-08-17T07:00:00Z", "snippet": "",
            "message_type": "human", "importance": "high", "action_required": 0,
            "keep_in_inbox": 1, "digest_worthy": 0, "confidence": 0.9, "reasoning": "r",
            "person_org_signal": None, "matched_person_id": None, "matched_org_ids": None,
            "processed_at": "2026-08-17T07:00:01Z", "run_at": run_at,
        })
    results = store.get_messages_for_run(conn, "2026-08-17 17:24")
    assert [m["gmail_message_id"] for m in results] == ["msg-2"]


def test_upsert_message_stores_label_applied():
    conn = store.init_db(":memory:")
    store.upsert_message(conn, {
        "gmail_message_id": "msg-1", "thread_id": "t", "sender_email": "a@x.com",
        "sender_name": "A", "subject": "s", "received_at": "2026-08-17T07:00:00Z", "snippet": "",
        "message_type": "human", "importance": "high", "action_required": 0,
        "keep_in_inbox": 1, "digest_worthy": 0, "confidence": 0.9, "reasoning": "r",
        "person_org_signal": None, "matched_person_id": "p1", "matched_org_ids": None,
        "processed_at": "2026-08-17T07:00:01Z", "run_at": "2026-08-17 17:24", "label_applied": "VIP",
    })
    row = conn.execute("SELECT label_applied FROM messages WHERE gmail_message_id = 'msg-1'").fetchone()
    assert row["label_applied"] == "VIP"


def test_get_recent_messages_limit_and_order():
    conn = store.init_db(":memory:")
    for i, received_at in enumerate(["2026-08-14T07:00:00Z", "2026-08-15T07:00:00Z", "2026-08-16T07:00:00Z"]):
        store.upsert_message(conn, {
            "gmail_message_id": f"msg-{i}", "thread_id": "t", "sender_email": "a@example.com",
            "sender_name": "A", "subject": f"subject-{i}", "received_at": received_at, "snippet": "",
            "message_type": "newsletter", "importance": "low", "action_required": 0,
            "keep_in_inbox": 1, "digest_worthy": 1, "confidence": 0.9, "reasoning": "r",
            "person_org_signal": None, "matched_person_id": None, "matched_org_ids": None,
            "processed_at": received_at,
        })
    results = store.get_recent_messages(conn, limit=2)
    assert [m["subject"] for m in results] == ["subject-2", "subject-1"]
