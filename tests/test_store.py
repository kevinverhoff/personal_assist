import store


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
