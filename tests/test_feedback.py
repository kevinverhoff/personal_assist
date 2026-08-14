import json

import store
from feedback import list_recent, record_correction


def test_list_recent_returns_messages():
    conn = store.init_db(":memory:")
    store.upsert_message(conn, {
        "gmail_message_id": "msg-1", "thread_id": "t", "sender_email": "a@x.com",
        "sender_name": "A", "subject": "Test subject", "received_at": "2026-08-15T07:00:00Z",
        "snippet": "", "message_type": "newsletter", "importance": "low", "action_required": 0,
        "keep_in_inbox": 1, "digest_worthy": 1, "confidence": 0.9, "reasoning": "r",
        "person_org_signal": None, "matched_person_id": None, "matched_org_ids": None,
        "processed_at": "2026-08-15T07:00:01Z",
    })
    recent = list_recent(conn, limit=5)
    assert len(recent) == 1
    assert recent[0]["subject"] == "Test subject"


def test_record_correction_stores_snapshot_and_correction():
    conn = store.init_db(":memory:")
    store.upsert_message(conn, {
        "gmail_message_id": "msg-1", "thread_id": "t", "sender_email": "a@x.com",
        "sender_name": "A", "subject": "Test subject", "received_at": "2026-08-15T07:00:00Z",
        "snippet": "", "message_type": "newsletter", "importance": "low", "action_required": 0,
        "keep_in_inbox": 1, "digest_worthy": 1, "confidence": 0.9, "reasoning": "r",
        "person_org_signal": None, "matched_person_id": None, "matched_org_ids": None,
        "processed_at": "2026-08-15T07:00:01Z",
    })
    record_correction(
        conn, "msg-1",
        original={"importance": "low"},
        corrected_fields={"importance": "high"},
        note="this was actually urgent",
    )
    rows = conn.execute("SELECT gmail_message_id, original_classification, corrected_fields, note FROM feedback").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "msg-1"
    assert json.loads(rows[0][1]) == {"importance": "low"}
    assert json.loads(rows[0][2]) == {"importance": "high"}
    assert rows[0][3] == "this was actually urgent"
