from unittest.mock import MagicMock, patch

import store


@patch("main.build_service")
@patch("main.fetch_new_messages")
@patch("main.make_client")
@patch("main.classify_message")
@patch("main.NotionClient")
@patch("main.PeopleCache")
@patch("main.reconcile_sender")
@patch("main.update_latest_run_page")
def test_run_processes_messages_and_updates_checkpoint(
    mock_update_page, mock_reconcile, mock_cache_cls, mock_notion_cls,
    mock_classify, mock_gemini_client, mock_fetch, mock_gmail_service, tmp_path, monkeypatch
):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "x")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "x")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("NOTION_TOKEN", "x")
    monkeypatch.setenv("NOTION_PEOPLE_DATA_SOURCE_ID", "x")
    monkeypatch.setenv("NOTION_ORGANIZATIONS_DATA_SOURCE_ID", "x")
    monkeypatch.setenv("NOTION_AFFILIATIONS_DATA_SOURCE_ID", "x")
    monkeypatch.setenv("NOTION_EMAIL_ADDRESSES_DATA_SOURCE_ID", "x")
    monkeypatch.setenv("NOTION_EMAIL_DIGESTS_DATA_SOURCE_ID", "x")
    monkeypatch.setenv("NOTION_EMAIL_AGENT_PARENT_PAGE_ID", "x")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("LOG_PATH", str(tmp_path / "log.md"))

    mock_fetch.return_value = ([{
        "gmail_message_id": "msg-1", "thread_id": "t1", "sender_email": "a@x.com",
        "sender_name": "A Sender", "subject": "Hi", "received_at": "2026-08-15T07:00:00Z",
        "snippet": "hi", "body": "hi there", "headers": {},
    }], "history-2")

    mock_classify.return_value = {
        "message_type": "human", "importance": "high", "action_required": True,
        "keep_in_inbox": True, "digest_worthy": False, "person_org_signal": None,
        "confidence": 0.9, "reasoning": "looks real",
    }
    mock_cache_cls.load.return_value = MagicMock(match_by_email=lambda e: None)
    mock_reconcile.return_value = {"action": "no_action"}

    import main
    result = main.run(dry_run=False)

    assert result["status"] == "ok"
    assert result["messages_processed"] == 1

    conn = store.init_db(str(tmp_path / "test.db"))
    rows = conn.execute("SELECT gmail_message_id FROM messages").fetchall()
    assert [r[0] for r in rows] == ["msg-1"]
    sync_state = conn.execute("SELECT last_history_id FROM sync_state").fetchone()
    assert sync_state[0] == "history-2"


@patch("main.build_service")
@patch("main.fetch_new_messages")
@patch("main.make_client")
@patch("main.classify_message")
@patch("main.NotionClient")
@patch("main.PeopleCache")
@patch("main.reconcile_sender")
@patch("main.update_latest_run_page")
def test_run_classifier_failure_keeps_message_in_inbox(
    mock_update_page, mock_reconcile, mock_cache_cls, mock_notion_cls,
    mock_classify, mock_gemini_client, mock_fetch, mock_gmail_service, tmp_path, monkeypatch
):
    for name, value in {
        "GOOGLE_CLIENT_ID": "x", "GOOGLE_CLIENT_SECRET": "x", "GOOGLE_REFRESH_TOKEN": "x",
        "GEMINI_API_KEY": "x", "NOTION_TOKEN": "x", "NOTION_PEOPLE_DATA_SOURCE_ID": "x",
        "NOTION_ORGANIZATIONS_DATA_SOURCE_ID": "x", "NOTION_AFFILIATIONS_DATA_SOURCE_ID": "x",
        "NOTION_EMAIL_ADDRESSES_DATA_SOURCE_ID": "x", "NOTION_EMAIL_DIGESTS_DATA_SOURCE_ID": "x",
        "NOTION_EMAIL_AGENT_PARENT_PAGE_ID": "x",
        "DB_PATH": str(tmp_path / "test.db"), "LOG_PATH": str(tmp_path / "log.md"),
    }.items():
        monkeypatch.setenv(name, value)

    mock_fetch.return_value = ([{
        "gmail_message_id": "msg-1", "thread_id": "t1", "sender_email": "a@x.com",
        "sender_name": "A Sender", "subject": "Hi", "received_at": "2026-08-15T07:00:00Z",
        "snippet": "hi", "body": "hi there", "headers": {},
    }], "history-2")
    mock_classify.return_value = {
        "message_type": "uncertain", "importance": "medium", "action_required": False,
        "keep_in_inbox": True, "digest_worthy": False, "person_org_signal": None,
        "confidence": 0.0, "reasoning": "Classification failed, defaulting to safe values: boom",
    }
    mock_cache_cls.load.return_value = MagicMock(match_by_email=lambda e: None)
    mock_reconcile.return_value = {"action": "no_action"}

    import main
    result = main.run(dry_run=False)
    assert result["status"] == "ok"

    conn = store.init_db(str(tmp_path / "test.db"))
    row = conn.execute("SELECT keep_in_inbox FROM messages WHERE gmail_message_id = 'msg-1'").fetchone()
    assert row[0] == 1
