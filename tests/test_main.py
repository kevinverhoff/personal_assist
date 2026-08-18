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


def _patch_main(test_func):
    """Applies the full set of main.py dependency patches every test needs,
    innermost-first so the wrapped test receives them in call order."""
    decorators = [
        patch("main.summarize_for_archive"),
        patch("main.update_latest_run_page"),
        patch("main.reconcile_sender"),
        patch("main.PeopleCache"),
        patch("main.NotionClient"),
        patch("main.classify_message"),
        patch("main.make_client"),
        patch("main.apply_label"),
        patch("main.get_or_create_label"),
        patch("main.archive_message"),
        patch("main.fetch_new_messages"),
        patch("main.build_service"),
    ]
    for decorator in reversed(decorators):
        test_func = decorator(test_func)
    return test_func


@_patch_main
def test_run_processes_messages_and_updates_checkpoint(
    mock_gmail_service, mock_fetch, mock_archive, mock_get_or_create_label, mock_apply_label,
    mock_gemini_client, mock_classify, mock_notion_cls, mock_cache_cls, mock_reconcile, mock_update_page,
    mock_summarize_for_archive,
    tmp_path, monkeypatch,
):
    _set_env(monkeypatch, tmp_path)
    mock_get_or_create_label.side_effect = ["vip-label-id", "known-label-id"]
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
    mock_apply_label.assert_not_called()  # sender not matched to a known Person


@_patch_main
def test_run_records_error_and_continues_when_one_message_fails(
    mock_gmail_service, mock_fetch, mock_archive, mock_get_or_create_label, mock_apply_label,
    mock_gemini_client, mock_classify, mock_notion_cls, mock_cache_cls, mock_reconcile, mock_update_page,
    mock_summarize_for_archive,
    tmp_path, monkeypatch,
):
    # Reproduces the real risk: a transient failure (Notion timeout, Gmail
    # hiccup, a message that vanished mid-run) in per-message side effects
    # must not crash the whole batch and strand sync_state -- it should be
    # logged and the run should keep going.
    _set_env(monkeypatch, tmp_path)
    mock_get_or_create_label.side_effect = ["vip-label-id", "known-label-id"]
    mock_fetch.return_value = (
        [_one_message(gmail_message_id="msg-1"), _one_message(gmail_message_id="msg-2")],
        "history-2",
    )
    mock_classify.return_value = {
        "message_type": "human", "importance": "medium", "action_required": False,
        "keep_in_inbox": True, "digest_worthy": False, "person_org_signal": None,
        "confidence": 0.9, "reasoning": "looks real",
    }
    mock_cache_cls.load.return_value = MagicMock(match_by_email=lambda e: None)
    mock_reconcile.side_effect = [RuntimeError("Notion timeout"), {"action": "no_action"}]

    import main
    result = main.run(dry_run=False)

    assert result["status"] == "ok_with_errors"
    assert result["messages_processed"] == 2

    conn = store.init_db(str(tmp_path / "test.db"))
    rows = conn.execute("SELECT gmail_message_id FROM messages").fetchall()
    assert [r[0] for r in rows] == ["msg-2"]  # msg-1 failed and was never persisted
    sync_state = conn.execute("SELECT last_history_id FROM sync_state").fetchone()
    assert sync_state[0] == "history-2"  # checkpoint still advances -- not stuck retrying msg-1 forever
    run_log_row = conn.execute("SELECT status, errors FROM run_log ORDER BY id DESC LIMIT 1").fetchone()
    assert run_log_row["status"] == "ok_with_errors"
    assert "msg-1" in run_log_row["errors"]
    assert "Notion timeout" in run_log_row["errors"]


@_patch_main
def test_run_classifier_failure_keeps_message_in_inbox(
    mock_gmail_service, mock_fetch, mock_archive, mock_get_or_create_label, mock_apply_label,
    mock_gemini_client, mock_classify, mock_notion_cls, mock_cache_cls, mock_reconcile, mock_update_page,
    mock_summarize_for_archive,
    tmp_path, monkeypatch,
):
    _set_env(monkeypatch, tmp_path)
    mock_get_or_create_label.side_effect = ["vip-label-id", "known-label-id"]
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


@_patch_main
def test_run_archives_routine_high_confidence_unmatched_message(
    mock_gmail_service, mock_fetch, mock_archive, mock_get_or_create_label, mock_apply_label,
    mock_gemini_client, mock_classify, mock_notion_cls, mock_cache_cls, mock_reconcile, mock_update_page,
    mock_summarize_for_archive,
    tmp_path, monkeypatch,
):
    _set_env(monkeypatch, tmp_path)
    mock_get_or_create_label.side_effect = ["vip-label-id", "known-label-id"]
    mock_fetch.return_value = ([_one_message(sender_email="news@x.com", sender_name="X Weekly", body="Full newsletter body.")], "history-2")
    mock_classify.return_value = {
        "message_type": "newsletter", "importance": "low", "action_required": False,
        "keep_in_inbox": False, "digest_worthy": True, "person_org_signal": None,
        "confidence": 0.97, "reasoning": "newsletter",
    }
    mock_cache_cls.load.return_value = MagicMock(match_by_email=lambda e: None)
    mock_reconcile.return_value = {"action": "no_action"}
    mock_summarize_for_archive.return_value = "This week's top story is about local elections."

    import main
    main.run(dry_run=False, archive=True)

    mock_archive.assert_called_once_with(mock_gmail_service.return_value, "msg-1")
    mock_summarize_for_archive.assert_called_once_with(mock_gemini_client.return_value, "Hi", "Full newsletter body.")
    conn = store.init_db(str(tmp_path / "test.db"))
    row = conn.execute("SELECT archived, archive_summary FROM messages WHERE gmail_message_id = 'msg-1'").fetchone()
    assert row["archived"] == 1
    assert row["archive_summary"] == "This week's top story is about local elections."


@_patch_main
def test_run_does_not_archive_when_matched_to_known_person(
    mock_gmail_service, mock_fetch, mock_archive, mock_get_or_create_label, mock_apply_label,
    mock_gemini_client, mock_classify, mock_notion_cls, mock_cache_cls, mock_reconcile, mock_update_page,
    mock_summarize_for_archive,
    tmp_path, monkeypatch,
):
    _set_env(monkeypatch, tmp_path)
    mock_get_or_create_label.side_effect = ["vip-label-id", "known-label-id"]
    mock_fetch.return_value = ([_one_message()], "history-2")
    mock_classify.return_value = {
        "message_type": "newsletter", "importance": "low", "action_required": False,
        "keep_in_inbox": False, "digest_worthy": True, "person_org_signal": None,
        "confidence": 0.99, "reasoning": "newsletter",
    }
    mock_cache_cls.load.return_value = MagicMock(
        match_by_email=lambda e: {"person_id": "p1", "person_name": "Someone", "importance": None}
    )
    mock_reconcile.return_value = {"action": "known", "person_id": "p1"}

    import main
    main.run(dry_run=False, archive=True)

    mock_archive.assert_not_called()


@_patch_main
def test_run_does_not_archive_when_archive_flag_is_false(
    mock_gmail_service, mock_fetch, mock_archive, mock_get_or_create_label, mock_apply_label,
    mock_gemini_client, mock_classify, mock_notion_cls, mock_cache_cls, mock_reconcile, mock_update_page,
    mock_summarize_for_archive,
    tmp_path, monkeypatch,
):
    _set_env(monkeypatch, tmp_path)
    mock_get_or_create_label.side_effect = ["vip-label-id", "known-label-id"]
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


@_patch_main
def test_run_does_not_archive_during_dry_run(
    mock_gmail_service, mock_fetch, mock_archive, mock_get_or_create_label, mock_apply_label,
    mock_gemini_client, mock_classify, mock_notion_cls, mock_cache_cls, mock_reconcile, mock_update_page,
    mock_summarize_for_archive,
    tmp_path, monkeypatch,
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
    mock_get_or_create_label.assert_not_called()  # dry-run touches nothing in Gmail
    mock_apply_label.assert_not_called()


@_patch_main
def test_run_applies_vip_label_for_vip_known_sender(
    mock_gmail_service, mock_fetch, mock_archive, mock_get_or_create_label, mock_apply_label,
    mock_gemini_client, mock_classify, mock_notion_cls, mock_cache_cls, mock_reconcile, mock_update_page,
    mock_summarize_for_archive,
    tmp_path, monkeypatch,
):
    _set_env(monkeypatch, tmp_path)
    mock_get_or_create_label.side_effect = ["vip-label-id", "known-label-id"]
    mock_fetch.return_value = ([_one_message(sender_email="cbarr@wicaa.org", sender_name="Carole Barr")], "history-2")
    mock_classify.return_value = {
        "message_type": "human", "importance": "high", "action_required": False,
        "keep_in_inbox": True, "digest_worthy": False, "person_org_signal": None,
        "confidence": 0.95, "reasoning": "known VIP contact",
    }
    mock_cache_cls.load.return_value = MagicMock(
        match_by_email=lambda e: {"person_id": "p1", "person_name": "Carole Barr", "importance": "VIP"}
    )
    mock_reconcile.return_value = {"action": "known", "person_id": "p1"}

    import main
    main.run(dry_run=False, archive=True)

    mock_apply_label.assert_called_once_with(mock_gmail_service.return_value, "msg-1", "vip-label-id")
    conn = store.init_db(str(tmp_path / "test.db"))
    row = conn.execute("SELECT run_at, label_applied FROM messages WHERE gmail_message_id = 'msg-1'").fetchone()
    assert row["label_applied"] == "VIP"
    assert row["run_at"] == conn.execute("SELECT last_run_at FROM sync_state").fetchone()[0]


@_patch_main
def test_run_applies_known_contact_label_for_non_vip_known_sender(
    mock_gmail_service, mock_fetch, mock_archive, mock_get_or_create_label, mock_apply_label,
    mock_gemini_client, mock_classify, mock_notion_cls, mock_cache_cls, mock_reconcile, mock_update_page,
    mock_summarize_for_archive,
    tmp_path, monkeypatch,
):
    _set_env(monkeypatch, tmp_path)
    mock_get_or_create_label.side_effect = ["vip-label-id", "known-label-id"]
    mock_fetch.return_value = ([_one_message(sender_email="brout@cityofgreencastle.com", sender_name="Blaine Rout")], "history-2")
    mock_classify.return_value = {
        "message_type": "human", "importance": "medium", "action_required": False,
        "keep_in_inbox": True, "digest_worthy": False, "person_org_signal": None,
        "confidence": 0.9, "reasoning": "known contact",
    }
    mock_cache_cls.load.return_value = MagicMock(
        match_by_email=lambda e: {"person_id": "p2", "person_name": "Blaine Rout", "importance": None}
    )
    mock_reconcile.return_value = {"action": "known", "person_id": "p2"}

    import main
    main.run(dry_run=False, archive=True)

    mock_apply_label.assert_called_once_with(mock_gmail_service.return_value, "msg-1", "known-label-id")
    conn = store.init_db(str(tmp_path / "test.db"))
    row = conn.execute("SELECT label_applied FROM messages WHERE gmail_message_id = 'msg-1'").fetchone()
    assert row["label_applied"] == "Known Contact"


@_patch_main
def test_run_stores_no_label_applied_for_unmatched_sender(
    mock_gmail_service, mock_fetch, mock_archive, mock_get_or_create_label, mock_apply_label,
    mock_gemini_client, mock_classify, mock_notion_cls, mock_cache_cls, mock_reconcile, mock_update_page,
    mock_summarize_for_archive,
    tmp_path, monkeypatch,
):
    _set_env(monkeypatch, tmp_path)
    mock_get_or_create_label.side_effect = ["vip-label-id", "known-label-id"]
    mock_fetch.return_value = ([_one_message()], "history-2")
    mock_classify.return_value = {
        "message_type": "human", "importance": "high", "action_required": True,
        "keep_in_inbox": True, "digest_worthy": False, "person_org_signal": None,
        "confidence": 0.9, "reasoning": "unknown sender",
    }
    mock_cache_cls.load.return_value = MagicMock(match_by_email=lambda e: None)
    mock_reconcile.return_value = {"action": "no_action"}

    import main
    main.run(dry_run=False)

    conn = store.init_db(str(tmp_path / "test.db"))
    row = conn.execute("SELECT label_applied FROM messages WHERE gmail_message_id = 'msg-1'").fetchone()
    assert row["label_applied"] is None
