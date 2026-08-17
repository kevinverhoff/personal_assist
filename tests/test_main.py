from unittest.mock import MagicMock, patch

import store

_ENV = {
    "GOOGLE_CLIENT_ID": "x", "GOOGLE_CLIENT_SECRET": "x", "GOOGLE_REFRESH_TOKEN": "x",
    "GEMINI_API_KEY": "x", "NOTION_TOKEN": "x", "NOTION_PEOPLE_DATA_SOURCE_ID": "x",
    "NOTION_ORGANIZATIONS_DATA_SOURCE_ID": "x", "NOTION_AFFILIATIONS_DATA_SOURCE_ID": "x",
    "NOTION_EMAIL_ADDRESSES_DATA_SOURCE_ID": "x", "NOTION_EMAIL_DIGESTS_DATA_SOURCE_ID": "x",
    "NOTION_EMAIL_AGENT_PARENT_PAGE_ID": "x",
}


def _set_env(monkeypatch, tmp_path):
    for name, value in _ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("LOG_PATH", str(tmp_path / "log.md"))


def _one_message(**overrides):
    base = {
        "gmail_message_id": "msg-1", "thread_id": "t1", "sender_email": "a@x.com",
        "sender_name": "A Sender", "subject": "Hi", "received_at": "2026-08-15T07:00:00Z",
        "snippet": "hi", "body": "hi there", "headers": {},
    }
    base.update(overrides)
    return base


@patch("main.archive_message")
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
    mock_classify, mock_gemini_client, mock_fetch, mock_gmail_service, mock_archive, tmp_path, monkeypatch
):
    _set_env(monkeypatch, tmp_path)
    mock_fetch.return_value = ([_one_message()], "history-2")
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
    mock_archive.assert_not_called()  # human message, not archive-eligible


@patch("main.archive_message")
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
    mock_classify, mock_gemini_client, mock_fetch, mock_gmail_service, mock_archive, tmp_path, monkeypatch
):
    _set_env(monkeypatch, tmp_path)
    mock_fetch.return_value = ([_one_message()], "history-2")
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
    mock_archive.assert_not_called()


@patch("main.archive_message")
@patch("main.build_service")
@patch("main.fetch_new_messages")
@patch("main.make_client")
@patch("main.classify_message")
@patch("main.NotionClient")
@patch("main.PeopleCache")
@patch("main.reconcile_sender")
@patch("main.update_latest_run_page")
def test_run_archives_routine_high_confidence_unmatched_message(
    mock_update_page, mock_reconcile, mock_cache_cls, mock_notion_cls,
    mock_classify, mock_gemini_client, mock_fetch, mock_gmail_service, mock_archive, tmp_path, monkeypatch
):
    _set_env(monkeypatch, tmp_path)
    mock_fetch.return_value = ([_one_message(sender_email="news@x.com", sender_name="X Weekly")], "history-2")
    mock_classify.return_value = {
        "message_type": "newsletter", "importance": "low", "action_required": False,
        "keep_in_inbox": False, "digest_worthy": True, "person_org_signal": None,
        "confidence": 0.97, "reasoning": "newsletter",
    }
    mock_cache_cls.load.return_value = MagicMock(match_by_email=lambda e: None)
    mock_reconcile.return_value = {"action": "no_action"}

    import main
    main.run(dry_run=False, archive=True)

    mock_archive.assert_called_once_with(mock_gmail_service.return_value, "msg-1")
    conn = store.init_db(str(tmp_path / "test.db"))
    row = conn.execute("SELECT archived FROM messages WHERE gmail_message_id = 'msg-1'").fetchone()
    assert row[0] == 1


@patch("main.archive_message")
@patch("main.build_service")
@patch("main.fetch_new_messages")
@patch("main.make_client")
@patch("main.classify_message")
@patch("main.NotionClient")
@patch("main.PeopleCache")
@patch("main.reconcile_sender")
@patch("main.update_latest_run_page")
def test_run_does_not_archive_when_matched_to_known_person(
    mock_update_page, mock_reconcile, mock_cache_cls, mock_notion_cls,
    mock_classify, mock_gemini_client, mock_fetch, mock_gmail_service, mock_archive, tmp_path, monkeypatch
):
    _set_env(monkeypatch, tmp_path)
    mock_fetch.return_value = ([_one_message()], "history-2")
    mock_classify.return_value = {
        "message_type": "newsletter", "importance": "low", "action_required": False,
        "keep_in_inbox": False, "digest_worthy": True, "person_org_signal": None,
        "confidence": 0.99, "reasoning": "newsletter",
    }
    mock_cache_cls.load.return_value = MagicMock(match_by_email=lambda e: {"person_id": "p1", "person_name": "Someone"})
    mock_reconcile.return_value = {"action": "known", "person_id": "p1"}

    import main
    main.run(dry_run=False, archive=True)

    mock_archive.assert_not_called()


@patch("main.archive_message")
@patch("main.build_service")
@patch("main.fetch_new_messages")
@patch("main.make_client")
@patch("main.classify_message")
@patch("main.NotionClient")
@patch("main.PeopleCache")
@patch("main.reconcile_sender")
@patch("main.update_latest_run_page")
def test_run_does_not_archive_when_archive_flag_is_false(
    mock_update_page, mock_reconcile, mock_cache_cls, mock_notion_cls,
    mock_classify, mock_gemini_client, mock_fetch, mock_gmail_service, mock_archive, tmp_path, monkeypatch
):
    _set_env(monkeypatch, tmp_path)
    mock_fetch.return_value = ([_one_message()], "history-2")
    mock_classify.return_value = {
        "message_type": "newsletter", "importance": "low", "action_required": False,
        "keep_in_inbox": False, "digest_worthy": True, "person_org_signal": None,
        "confidence": 0.99, "reasoning": "newsletter",
    }
    mock_cache_cls.load.return_value = MagicMock(match_by_email=lambda e: None)
    mock_reconcile.return_value = {"action": "no_action"}

    import main
    main.run(dry_run=False, archive=False)

    mock_archive.assert_not_called()


@patch("main.archive_message")
@patch("main.build_service")
@patch("main.fetch_new_messages")
@patch("main.make_client")
@patch("main.classify_message")
@patch("main.NotionClient")
@patch("main.PeopleCache")
@patch("main.reconcile_sender")
@patch("main.update_latest_run_page")
def test_run_does_not_archive_during_dry_run(
    mock_update_page, mock_reconcile, mock_cache_cls, mock_notion_cls,
    mock_classify, mock_gemini_client, mock_fetch, mock_gmail_service, mock_archive, tmp_path, monkeypatch
):
    _set_env(monkeypatch, tmp_path)
    mock_fetch.return_value = ([_one_message()], "history-2")
    mock_classify.return_value = {
        "message_type": "newsletter", "importance": "low", "action_required": False,
        "keep_in_inbox": False, "digest_worthy": True, "person_org_signal": None,
        "confidence": 0.99, "reasoning": "newsletter",
    }
    mock_cache_cls.load.return_value = MagicMock(match_by_email=lambda e: None)
    mock_reconcile.return_value = {"action": "no_action"}

    import main
    main.run(dry_run=True, archive=True)

    mock_archive.assert_not_called()
