import argparse
import datetime

from archive_summary import summarize_for_archive
from archiving import should_archive
from classifier import classify_message, make_client
from config import load_config
from gmail_client import build_service, fetch_new_messages, archive_message, get_or_create_label, apply_label
from notion_client import NotionClient
from people_lookup import PeopleCache
from reconciliation import reconcile_sender
from agent_log import append_run_summary, update_latest_run_page
from signals import extract_signals
import store


# Gmail's colored "SuperStars" are UI-only and not exposed via the API at
# all (not even the plain star can be recolored) -- real labels are the
# closest API-controllable equivalent, using colors from Gmail's documented
# allowed palette (https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.labels#Label.Color).
VIP_LABEL_NAME = "VIP"
VIP_LABEL_COLOR = ("#fb4c2f", "#ffffff")
KNOWN_CONTACT_LABEL_NAME = "Known Contact"
KNOWN_CONTACT_LABEL_COLOR = ("#fad165", "#000000")


def run(dry_run: bool = False, archive: bool = True) -> dict:
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

    vip_label_id, known_label_id = None, None
    if not dry_run:
        vip_label_id = get_or_create_label(gmail_service, VIP_LABEL_NAME, *VIP_LABEL_COLOR)
        known_label_id = get_or_create_label(gmail_service, KNOWN_CONTACT_LABEL_NAME, *KNOWN_CONTACT_LABEL_COLOR)

    notion_client = NotionClient(config.notion_token)
    people_cache = PeopleCache.load(notion_client, config)
    gemini_client = make_client(config.gemini_api_key)

    results, unmatched, errors, archived = [], [], [], []

    for message in messages:
        sig = extract_signals(message["headers"], message["sender_email"])
        person_match = people_cache.match_by_email(message["sender_email"])
        classification = classify_message(
            gemini_client, message["subject"], message["snippet"], message["body"], sig, person_match
        )

        label_applied = None
        if not dry_run and person_match:
            is_vip = person_match.get("importance") == "VIP"
            label_applied = VIP_LABEL_NAME if is_vip else KNOWN_CONTACT_LABEL_NAME
            apply_label(gmail_service, message["gmail_message_id"], vip_label_id if is_vip else known_label_id)

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
            "run_at": run_at,
            "label_applied": label_applied,
        }
        if not dry_run:
            store.upsert_message(conn, row)
        result = {**row, "action_required": bool(row["action_required"]), "keep_in_inbox": bool(row["keep_in_inbox"])}
        results.append(result)

        if archive and not dry_run and should_archive(classification, person_match):
            archive_message(gmail_service, message["gmail_message_id"])
            archived_at = datetime.datetime.now(datetime.UTC).isoformat()
            archive_summary = summarize_for_archive(gemini_client, message["subject"], message["body"])
            store.mark_archived(conn, message["gmail_message_id"], archived_at, archive_summary)
            result["archive_summary"] = archive_summary
            archived.append(result)

    markdown = append_run_summary(config.log_path, run_at, results, unmatched, errors, archived=archived)
    if not dry_run:
        update_latest_run_page(notion_client, config, conn, markdown)
        store.set_sync_state(conn, new_history_id, run_at)
        store.insert_run_log(conn, run_at, len(messages), "ok", None)

    return {"status": "ok", "messages_processed": len(messages)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-archive", action="store_true", help="Classify and store as usual, but never archive anything.")
    args = parser.parse_args()
    outcome = run(dry_run=args.dry_run, archive=not args.no_archive)
    print(outcome)
