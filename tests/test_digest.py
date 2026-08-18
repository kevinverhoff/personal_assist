import json
from unittest.mock import MagicMock

from email_agent.digest import group_routine_messages, phrase_digest, generate_digest


def test_group_routine_messages_counts_and_groups_by_type_and_sender():
    messages = [
        {"message_type": "newsletter", "sender_name": "X Weekly", "digest_worthy": 1},
        {"message_type": "newsletter", "sender_name": "Y News", "digest_worthy": 1},
        {"message_type": "notification", "sender_name": "Library", "digest_worthy": 1},
    ]
    groups = group_routine_messages(messages)
    assert groups["newsletter"]["count"] == 2
    assert set(groups["newsletter"]["senders"]) == {"X Weekly", "Y News"}
    assert groups["notification"]["count"] == 1


def test_group_routine_messages_tracks_archived_count():
    messages = [
        {"message_type": "newsletter", "sender_name": "X Weekly", "digest_worthy": 1, "archived": 1},
        {"message_type": "newsletter", "sender_name": "Y News", "digest_worthy": 1, "archived": 0},
        {"message_type": "receipt", "sender_name": "Store", "digest_worthy": 1, "archived": 1},
    ]
    groups = group_routine_messages(messages)
    assert groups["newsletter"]["archived_count"] == 1
    assert groups["newsletter"]["count"] == 2
    assert groups["receipt"]["archived_count"] == 1


def test_group_routine_messages_ignores_non_digest_worthy():
    messages = [{"message_type": "human", "sender_name": "Blaine Rout", "digest_worthy": 0}]
    groups = group_routine_messages(messages)
    assert groups == {}


def test_phrase_digest_passes_exact_groups_to_gemini():
    client = MagicMock()
    response = MagicMock()
    response.text = "You received 2 newsletters from X Weekly and Y News."
    client.models.generate_content.return_value = response

    groups = {"newsletter": {"count": 2, "senders": ["X Weekly", "Y News"]}}
    text = phrase_digest(client, groups)

    assert text == "You received 2 newsletters from X Weekly and Y News."
    prompt = client.models.generate_content.call_args.kwargs["contents"]
    assert json.dumps(groups) in prompt or "X Weekly" in prompt


def _message(**overrides):
    base = {
        "gmail_message_id": "msg-1", "message_type": "human", "importance": "medium",
        "action_required": 0, "matched_person_id": None, "digest_worthy": 0,
        "subject": "Hi", "sender_name": "A Sender", "sender_email": "a@example.com",
    }
    base.update(overrides)
    return base


def test_generate_digest_sections_known_attention_and_routine_are_mutually_exclusive():
    known = _message(gmail_message_id="m1", matched_person_id="p1", message_type="human",
                      subject="Draft", sender_name="Blaine Rout", sender_email="brout@cityofgreencastle.com")
    attention = _message(gmail_message_id="m2", importance="high",
                          subject="Security alert", sender_name="Google", sender_email="no-reply@accounts.google.com")
    routine = _message(gmail_message_id="m3", message_type="newsletter", digest_worthy=1,
                        subject="Weekly News", sender_name="X Weekly", sender_email="news@x.com")

    conn = MagicMock()
    config = MagicMock()
    config.notion_email_digests_data_source_id = "digests-ds"
    notion_client = MagicMock()
    notion_client.create_page.return_value = {"id": "digest-page-1"}
    gemini_client = MagicMock()
    gemini_response = MagicMock()
    gemini_response.text = "You received 1 newsletter from X Weekly."
    gemini_client.models.generate_content.return_value = gemini_response

    import email_agent.store as store_module
    original_get_messages = store_module.get_messages_in_window
    store_module.get_messages_in_window = lambda conn, start, end: [known, attention, routine]
    try:
        generate_digest(config, conn, notion_client, gemini_client, "daily")
    finally:
        store_module.get_messages_in_window = original_get_messages

    content_children = notion_client.create_page.call_args.kwargs["content"]
    assert "Blaine Rout" in content_children  # known person section
    assert "Google" in content_children  # attention section
    assert "X Weekly" in content_children  # routine phrasing
    # the routine message must not also be double-counted as "attention"
    assert "news@x.com" not in content_children.split("## Routine mail")[0]


def test_generate_digest_lists_archived_messages_with_summaries():
    archived = _message(gmail_message_id="m1", message_type="newsletter", digest_worthy=1,
                         subject="Weekly News", sender_name="X Weekly", sender_email="news@x.com",
                         archived=1, archive_summary="Top story: local elections. https://x.com/news/1")
    kept = _message(gmail_message_id="m2", message_type="receipt", digest_worthy=1,
                     subject="Your receipt", sender_name="Store", sender_email="no-reply@store.com",
                     archived=0)

    conn = MagicMock()
    config = MagicMock()
    config.notion_email_digests_data_source_id = "digests-ds"
    notion_client = MagicMock()
    notion_client.create_page.return_value = {"id": "digest-page-1"}
    gemini_client = MagicMock()
    gemini_response = MagicMock()
    gemini_response.text = "You received 1 newsletter and 1 receipt."
    gemini_client.models.generate_content.return_value = gemini_response

    import email_agent.store as store_module
    original_get_messages = store_module.get_messages_in_window
    store_module.get_messages_in_window = lambda conn, start, end: [archived, kept]
    try:
        generate_digest(config, conn, notion_client, gemini_client, "daily")
    finally:
        store_module.get_messages_in_window = original_get_messages

    content = notion_client.create_page.call_args.kwargs["content"]
    assert '- "Weekly News" — X Weekly (news@x.com): Top story: local elections. https://x.com/news/1' in content
    assert "Your receipt" not in content.split("## Archived")[1]  # only archived ones listed here


def test_generate_digest_archived_section_shows_none_when_nothing_archived():
    kept = _message(gmail_message_id="m1", message_type="receipt", digest_worthy=1,
                     subject="Your receipt", sender_name="Store", sender_email="no-reply@store.com", archived=0)

    conn = MagicMock()
    config = MagicMock()
    config.notion_email_digests_data_source_id = "digests-ds"
    notion_client = MagicMock()
    notion_client.create_page.return_value = {"id": "digest-page-1"}
    gemini_client = MagicMock()
    gemini_response = MagicMock()
    gemini_response.text = "You received 1 receipt."
    gemini_client.models.generate_content.return_value = gemini_response

    import email_agent.store as store_module
    original_get_messages = store_module.get_messages_in_window
    store_module.get_messages_in_window = lambda conn, start, end: [kept]
    try:
        generate_digest(config, conn, notion_client, gemini_client, "daily")
    finally:
        store_module.get_messages_in_window = original_get_messages

    content = notion_client.create_page.call_args.kwargs["content"]
    assert "## Archived" in content
    assert "None." in content.split("## Archived")[1]


def test_generate_digest_current_period_uses_latest_run_and_action_notes():
    known = _message(gmail_message_id="m1", matched_person_id="p1", message_type="human",
                      subject="Draft", sender_name="Blaine Rout", sender_email="brout@cityofgreencastle.com",
                      archived=0, label_applied="Known Contact")
    attention = _message(gmail_message_id="m2", importance="high", archived=1, label_applied=None,
                          subject="Security alert", sender_name="Google", sender_email="no-reply@accounts.google.com")

    conn = MagicMock()
    config = MagicMock()
    config.notion_email_digests_data_source_id = "digests-ds"
    notion_client = MagicMock()
    notion_client.create_page.return_value = {"id": "digest-page-1"}
    gemini_client = MagicMock()
    gemini_response = MagicMock()
    gemini_response.text = "Nothing routine to report."
    gemini_client.models.generate_content.return_value = gemini_response

    import email_agent.store as store_module
    original_get_latest_run_at = store_module.get_latest_run_at
    original_get_messages_for_run = store_module.get_messages_for_run
    store_module.get_latest_run_at = lambda conn: "2026-08-17 17:24"
    store_module.get_messages_for_run = lambda conn, run_at: [known, attention] if run_at == "2026-08-17 17:24" else []
    try:
        generate_digest(config, conn, notion_client, gemini_client, "current")
    finally:
        store_module.get_latest_run_at = original_get_latest_run_at
        store_module.get_messages_for_run = original_get_messages_for_run

    content = notion_client.create_page.call_args.kwargs["content"]
    assert "Blaine Rout" in content and "labeled Known Contact" in content
    assert "Google" in content and "archived" in content

    properties = notion_client.create_page.call_args.kwargs["properties"]
    assert properties["Period"]["select"]["name"] == "Current"
    assert properties["Date"]["date"]["start"] == "2026-08-17T17:24:00+00:00"
    assert "2026-08-17 17:24" in properties["Digest"]["title"][0]["text"]["content"]


def test_generate_digest_current_period_with_no_successful_run_yet():
    conn = MagicMock()
    config = MagicMock()
    config.notion_email_digests_data_source_id = "digests-ds"
    notion_client = MagicMock()
    notion_client.create_page.return_value = {"id": "digest-page-1"}
    gemini_client = MagicMock()
    gemini_response = MagicMock()
    gemini_response.text = "Nothing routine to report."
    gemini_client.models.generate_content.return_value = gemini_response

    import email_agent.store as store_module
    original_get_latest_run_at = store_module.get_latest_run_at
    store_module.get_latest_run_at = lambda conn: None
    try:
        generate_digest(config, conn, notion_client, gemini_client, "current")
    finally:
        store_module.get_latest_run_at = original_get_latest_run_at

    content = notion_client.create_page.call_args.kwargs["content"]
    assert "None." in content
