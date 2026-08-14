import argparse
import datetime
import json

from classifier import make_client
from config import load_config
from notion_client import NotionClient
import store

_DIGEST_MODEL = "gemini-flash-lite-latest"


def group_routine_messages(messages: list[dict]) -> dict:
    groups: dict = {}
    for message in messages:
        if not message.get("digest_worthy"):
            continue
        message_type = message["message_type"]
        groups.setdefault(message_type, {"count": 0, "senders": []})
        groups[message_type]["count"] += 1
        sender = message["sender_name"]
        if sender not in groups[message_type]["senders"]:
            groups[message_type]["senders"].append(sender)
    return groups


def build_attention_recap(messages: list[dict]) -> list[str]:
    recap = []
    for message in messages:
        if message.get("importance") == "high" or message.get("importance") == "critical" or message.get("action_required"):
            recap.append(f"- {message['sender_name']}: \"{message['subject']}\" — {message['reasoning']}")
    return recap


def phrase_digest(gemini_client, groups: dict) -> str:
    if not groups:
        return "Nothing routine to report."
    prompt = (
        "Write 1-3 natural, conversational sentences summarizing this person's routine "
        "email for the period, using ONLY the exact counts and names given below — do not "
        "invent or alter any number or name.\n\n"
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
    groups = group_routine_messages(messages)
    recap = build_attention_recap(messages)
    routine_text = phrase_digest(gemini_client, groups)
    routine_count = sum(g["count"] for g in groups.values())

    body_lines = ["## Needs your attention"]
    body_lines.extend(recap if recap else ["Nothing needed your attention this period."])
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
            "Needs Attention Count": {"number": len(recap)},
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
