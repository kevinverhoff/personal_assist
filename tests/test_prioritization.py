from prioritization import group_messages, format_compact_line, is_attention_worthy, importance_sort_key


def _message(**overrides):
    base = {
        "gmail_message_id": "msg-1", "message_type": "human", "importance": "medium",
        "action_required": 0, "matched_person_id": None, "subject": "Hi",
        "sender_name": "A Sender", "sender_email": "a@example.com",
    }
    base.update(overrides)
    return base


def test_format_compact_line_matches_feedback_style():
    line = format_compact_line(_message(message_type="newsletter", subject="Weekly News", sender_name="X Weekly", sender_email="news@x.com"))
    assert line == '- [newsletter] "Weekly News" — X Weekly (news@x.com)'


def test_is_attention_worthy_true_for_high_importance():
    assert is_attention_worthy(_message(importance="high")) is True


def test_is_attention_worthy_true_for_action_required():
    assert is_attention_worthy(_message(importance="low", action_required=1)) is True


def test_is_attention_worthy_false_for_low_importance_no_action():
    assert is_attention_worthy(_message(importance="low", action_required=0)) is False


def test_importance_sort_key_orders_critical_first():
    messages = [_message(importance="low"), _message(importance="critical"), _message(importance="medium")]
    messages.sort(key=importance_sort_key)
    assert [m["importance"] for m in messages] == ["critical", "medium", "low"]


def test_group_messages_partitions_known_attention_rest():
    known_msg = _message(gmail_message_id="m1", matched_person_id="p1", importance="low")
    attention_msg = _message(gmail_message_id="m2", matched_person_id=None, importance="high")
    rest_msg = _message(gmail_message_id="m3", matched_person_id=None, importance="low", action_required=0)

    groups = group_messages([known_msg, attention_msg, rest_msg])

    assert [m["gmail_message_id"] for m in groups["known"]] == ["m1"]
    assert [m["gmail_message_id"] for m in groups["attention"]] == ["m2"]
    assert [m["gmail_message_id"] for m in groups["rest"]] == ["m3"]


def test_group_messages_sorts_known_and_attention_by_importance():
    low = _message(gmail_message_id="m1", matched_person_id="p1", importance="low")
    critical = _message(gmail_message_id="m2", matched_person_id="p1", importance="critical")

    groups = group_messages([low, critical])

    assert [m["gmail_message_id"] for m in groups["known"]] == ["m2", "m1"]
