import os

_NOTION_PAGES_SCHEMA = """
CREATE TABLE IF NOT EXISTS notion_pages (
  key TEXT PRIMARY KEY,
  page_id TEXT
);
"""


def _format_result_line(result: dict) -> str:
    flags = f"[{result['message_type']} / {result['importance']}"
    if result.get("action_required"):
        flags += " / action_required"
    flags += "]"
    return (
        f"- {flags} \"{result['subject']}\" — {result['sender_name']} "
        f"({result['sender_email']}) — {result['reasoning']}. "
        f"keep_in_inbox={result['keep_in_inbox']}, confidence={result['confidence']}"
    )


def append_run_summary(log_path: str, run_at: str, results: list[dict], unmatched: list[dict], errors: list[str]) -> str:
    lines = [f"## Run {run_at}", "", f"Processed {len(results)} messages ({len(unmatched)} unmatched senders).", ""]
    for result in results:
        lines.append(_format_result_line(result))
    if unmatched:
        lines.append("")
        lines.append("**Unmatched senders (real person, not in People DB):**")
        for person in unmatched:
            lines.append(f"- {person['sender_email']} — \"{person['sender_name']}\" — re: \"{person['subject']}\"")
    lines.append("")
    lines.append("No errors this run." if not errors else f"Errors: {errors}")
    lines.append("")
    section = "\n".join(lines)

    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(section + "\n")
    return section


def update_latest_run_page(client, config, conn, markdown: str) -> str:
    conn.executescript(_NOTION_PAGES_SCHEMA)
    conn.commit()
    row = conn.execute("SELECT page_id FROM notion_pages WHERE key = 'latest_run'").fetchone()

    if row is None:
        page = client.create_standalone_page("Email Agent — Latest Run", content=markdown)
        page_id = page["id"]
        conn.execute(
            "INSERT INTO notion_pages (key, page_id) VALUES ('latest_run', ?)", (page_id,)
        )
        conn.commit()
        return page_id

    page_id = row["page_id"]
    client.update_page(page_id, properties=None)
    return page_id
