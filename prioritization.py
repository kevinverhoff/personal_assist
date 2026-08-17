_IMPORTANCE_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}


def importance_sort_key(message: dict) -> int:
    return -_IMPORTANCE_RANK.get(message.get("importance", "low"), 0)


def is_attention_worthy(message: dict) -> bool:
    return message.get("importance") in ("critical", "high") or bool(message.get("action_required"))


def format_compact_line(message: dict) -> str:
    return f"- [{message['message_type']}] \"{message['subject']}\" — {message['sender_name']} ({message['sender_email']})"


def format_action_note(message: dict) -> str:
    if message.get("archived"):
        return "archived"
    if message.get("label_applied"):
        return f"labeled {message['label_applied']}"
    return "kept in inbox"


def format_compact_line_with_action(message: dict) -> str:
    return f"{format_compact_line(message)} — {format_action_note(message)}"


def group_messages(messages: list[dict]) -> dict:
    known, attention, rest = [], [], []
    for message in messages:
        if message.get("matched_person_id"):
            known.append(message)
        elif is_attention_worthy(message):
            attention.append(message)
        else:
            rest.append(message)
    known.sort(key=importance_sort_key)
    attention.sort(key=importance_sort_key)
    return {"known": known, "attention": attention, "rest": rest}
