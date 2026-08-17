import json
from unittest.mock import MagicMock

from digest import group_routine_messages, phrase_digest, generate_digest


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

    import store as store_module
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
