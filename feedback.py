import datetime
import json

from config import load_config
import store


def list_recent(conn, limit: int = 10) -> list[dict]:
    return store.get_recent_messages(conn, limit)


def record_correction(conn, gmail_message_id: str, original: dict, corrected_fields: dict, note: str) -> None:
    store.insert_feedback(
        conn,
        gmail_message_id=gmail_message_id,
        original_classification=json.dumps(original),
        corrected_fields=json.dumps(corrected_fields),
        note=note,
        corrected_at=datetime.datetime.now(datetime.UTC).isoformat(),
    )


def _prompt_for_correction(message: dict) -> tuple[dict, str]:
    print(f"\nSubject: {message['subject']}")
    print(f"From: {message['sender_name']} <{message['sender_email']}>")
    print(f"Current: type={message['message_type']}, importance={message['importance']}, "
          f"action_required={bool(message['action_required'])}, keep_in_inbox={bool(message['keep_in_inbox'])}")

    corrected = {}
    new_importance = input("Correct importance (critical/high/medium/low, blank to skip): ").strip()
    if new_importance:
        corrected["importance"] = new_importance
    new_type = input("Correct message_type (blank to skip): ").strip()
    if new_type:
        corrected["message_type"] = new_type
    note = input("Note (why was this wrong?): ").strip()
    return corrected, note


def main():
    config = load_config()
    conn = store.init_db(config.db_path)
    recent = list_recent(conn, limit=10)

    for i, message in enumerate(recent):
        print(f"{i}: [{message['message_type']}] {message['subject']} — {message['sender_name']}")

    choice = input("\nWhich message needs a correction (index, or blank to quit)? ").strip()
    if not choice:
        return
    message = recent[int(choice)]
    corrected_fields, note = _prompt_for_correction(message)
    original = {
        "message_type": message["message_type"],
        "importance": message["importance"],
        "action_required": bool(message["action_required"]),
        "keep_in_inbox": bool(message["keep_in_inbox"]),
    }
    record_correction(conn, message["gmail_message_id"], original, corrected_fields, note)
    print("Recorded.")


if __name__ == "__main__":
    main()
