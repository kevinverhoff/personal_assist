import json
from unittest.mock import MagicMock

from digest import group_routine_messages, phrase_digest, build_attention_recap


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


def test_group_routine_messages_ignores_non_digest_worthy():
    messages = [{"message_type": "human", "sender_name": "Blaine Rout", "digest_worthy": 0}]
    groups = group_routine_messages(messages)
    assert groups == {}


def test_build_attention_recap_includes_high_importance_and_action_required():
    messages = [
        {"importance": "high", "action_required": 1, "sender_name": "Blaine Rout", "subject": "Draft", "reasoning": "needs feedback"},
        {"importance": "low", "action_required": 0, "sender_name": "X Weekly", "subject": "Newsletter", "reasoning": "routine"},
    ]
    recap = build_attention_recap(messages)
    assert len(recap) == 1
    assert "Blaine Rout" in recap[0]


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
