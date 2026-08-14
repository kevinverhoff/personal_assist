import argparse
import datetime

from classifier import classify_message, make_client
from config import load_config
from gmail_client import build_service, fetch_new_messages
from notion_client import NotionClient
from people_lookup import PeopleCache
from reconciliation import reconcile_sender
from agent_log import append_run_summary, update_latest_run_page
from signals import extract_signals
import store


def run(dry_run: bool = False) -> dict:
    config = load_config()
    conn = store.init_db(config.db_path)
    run_at = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M")

    try:
        gmail_service = build_service(config)
        sync_state = store.get_sync_state(conn)
        last_history_id = sync_state["last_history_id"] if sync_state else None
        messages, new_history_id = fetch_new_messages(gmail_service, last_history_id)
    except Exception as error:
        store.insert_run_log(conn, run_at, 0, "auth_error", str(error))
        return {"status": "auth_error", "messages_processed": 0}

    notion_client = NotionClient(config.notion_token)
    people_cache = PeopleCache.load(notion_client, config)
    gemini_client = make_client(config.gemini_api_key)

    results, unmatched, errors = [], [], []

    for message in messages:
        sig = extract_signals(message["headers"], message["sender_email"])
        person_match = people_cache.match_by_email(message["sender_email"])
        classification = classify_message(
            gemini_client, message["subject"], message["snippet"], message["body"], sig, person_match
        )

        is_human = classification["message_type"] == "human"
        reconciliation_result = reconcile_sender(
            notion_client, config, people_cache, message["sender_email"],
            message["sender_name"], is_human, dry_run,
        )
        if reconciliation_result["action"] in ("created_person",) and not person_match:
            unmatched.append({
                "sender_email": message["sender_email"],
                "sender_name": message["sender_name"],
                "subject": message["subject"],
            })

        row = {
            "gmail_message_id": message["gmail_message_id"],
            "thread_id": message["thread_id"],
            "sender_email": message["sender_email"],
            "sender_name": message["sender_name"],
            "subject": message["subject"],
            "received_at": message["received_at"],
            "snippet": message["snippet"],
            "message_type": classification["message_type"],
            "importance": classification["importance"],
            "action_required": int(classification["action_required"]),
            "keep_in_inbox": int(classification["keep_in_inbox"]),
            "digest_worthy": int(classification["digest_worthy"]),
            "confidence": classification["confidence"],
            "reasoning": classification["reasoning"],
            "person_org_signal": classification["person_org_signal"],
            "matched_person_id": person_match["person_id"] if person_match else None,
            "matched_org_ids": None,
            "processed_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        if not dry_run:
            store.upsert_message(conn, row)
        results.append({**row, "action_required": bool(row["action_required"]), "keep_in_inbox": bool(row["keep_in_inbox"])})

    markdown = append_run_summary(config.log_path, run_at, results, unmatched, errors)
    if not dry_run:
        update_latest_run_page(notion_client, config, conn, markdown)
        store.set_sync_state(conn, new_history_id, run_at)
        store.insert_run_log(conn, run_at, len(messages), "ok", None)

    return {"status": "ok", "messages_processed": len(messages)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    outcome = run(dry_run=args.dry_run)
    print(outcome)
