import argparse
import datetime
import json

from classifier import make_client
from config import load_config
from notion_client import NotionClient
from prioritization import group_messages, format_compact_line
import store

_DIGEST_MODEL = "gemini-flash-lite-latest"


def group_routine_messages(messages: list[dict]) -> dict:
    groups: dict = {}
    for message in messages:
        if not message.get("digest_worthy"):
            continue
        message_type = message["message_type"]
        groups.setdefault(message_type, {"count": 0, "senders": [], "archived_count": 0})
        groups[message_type]["count"] += 1
        if message.get("archived"):
            groups[message_type]["archived_count"] += 1
        sender = message["sender_name"]
        if sender not in groups[message_type]["senders"]:
            groups[message_type]["senders"].append(sender)
    return groups


def phrase_digest(gemini_client, groups: dict) -> str:
    if not groups:
        return "Nothing routine to report."
    prompt = (
        "Write 1-3 natural, conversational sentences summarizing this person's routine "
        "email for the period, using ONLY the exact counts and names given below — do not "
        "invent or alter any number or name. Each group has a count, a list of senders, and "
        "an archived_count (how many of that count were already archived out of the inbox, "
        "vs. left for review) — mention how many were archived if archived_count is greater "
        "than zero and less than count; if archived_count equals count, say they were all "
        "archived; if archived_count is zero, don't mention archiving for that group.\n\n"
        f"{json.dumps(groups)}"
    )
    response = gemini_client.models.generate_content(model=_DIGEST_MODEL, contents=prompt)
    return response.text


def generate_digest(config, conn, notion_client, gemini_client, period: str) -> str:
    now = datetime.datetime.now(datetime.UTC)
    if period == "daily":
        start = (now - datetime.timedelta(days=1)).isoformat()
    else:
        start = (now - datetime.timedelta(days=7)).isoformat()
    end = now.isoformat()

    messages = store.get_messages_in_window(conn, start, end)
    sections = group_messages(messages)
    routine_groups = group_routine_messages(sections["rest"])
    routine_text = phrase_digest(gemini_client, routine_groups)
    routine_count = sum(g["count"] for g in routine_groups.values())

    body_lines = [f"## From people you know ({len(sections['known'])})"]
    if sections["known"]:
        body_lines.extend(format_compact_line(m) for m in sections["known"])
    else:
        body_lines.append("None.")
    body_lines.append("")
    body_lines.append(f"## May need your attention ({len(sections['attention'])})")
    if sections["attention"]:
        body_lines.extend(format_compact_line(m) for m in sections["attention"])
    else:
        body_lines.append("None.")
    body_lines.append("")
    body_lines.append("## Routine mail")
    body_lines.append(routine_text)
    content = "\n".join(body_lines)

    title = f"{period.capitalize()} Digest — {now.strftime('%Y-%m-%d')}"
    page = notion_client.create_page(
        config.notion_email_digests_data_source_id,
        properties={
            "Digest": {"title": [{"text": {"content": title}}]},
            "Period": {"select": {"name": period.capitalize()}},
            "Date": {"date": {"start": now.strftime("%Y-%m-%d")}},
            "Needs Attention Count": {"number": len(sections["attention"])},
            "Routine Count": {"number": routine_count},
        },
        content=content,
    )
    return page["id"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", choices=["daily", "weekly"], required=True)
    args = parser.parse_args()

    cfg = load_config()
    connection = store.init_db(cfg.db_path)
    client = NotionClient(cfg.notion_token)
    gemini = make_client(cfg.gemini_api_key)
    page_id = generate_digest(cfg, connection, client, gemini, args.period)
    print(f"Digest created: {page_id}")
