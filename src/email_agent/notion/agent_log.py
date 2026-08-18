import os

from email_agent.prioritization import group_messages, format_compact_line

_NOTION_PAGES_SCHEMA = """
CREATE TABLE IF NOT EXISTS notion_pages (
  key TEXT PRIMARY KEY,
  page_id TEXT
);
"""


def _append_group(lines: list[str], title: str, messages: list[dict]) -> None:
    lines.append(f"### {title} ({len(messages)})")
    if messages:
        lines.extend(format_compact_line(m) for m in messages)
    else:
        lines.append("None.")
    lines.append("")


def append_run_summary(
    log_path: str, run_at: str, results: list[dict], unmatched: list[dict], errors: list[str],
    archived: list[dict] | None = None,
) -> str:
    archived = archived or []
    groups = group_messages(results)

    lines = [
        f"## Run {run_at}", "",
        f"Processed {len(results)} messages "
        f"({len(unmatched)} unmatched senders, {len(archived)} archived).",
        "",
    ]
    _append_group(lines, "From people you know", groups["known"])
    _append_group(lines, "May need your attention", groups["attention"])
    _append_group(lines, "Everything else", groups["rest"])

    if archived:
        _append_group(lines, "Archived this run", archived)

    if unmatched:
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
        page = client.create_child_page(
            config.notion_email_agent_parent_page_id, "Email Agent — Latest Run", content=markdown
        )
        page_id = page["id"]
        conn.execute(
            "INSERT INTO notion_pages (key, page_id) VALUES ('latest_run', ?)", (page_id,)
        )
        conn.commit()
        return page_id

    page_id = row["page_id"]
    client.replace_page_content(page_id, markdown)
    return page_id
