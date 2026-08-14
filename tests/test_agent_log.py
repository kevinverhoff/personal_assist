import os
from unittest.mock import MagicMock

import store
from agent_log import append_run_summary, update_latest_run_page


def test_append_run_summary_writes_markdown(tmp_path):
    log_path = str(tmp_path / "agent_log.md")
    results = [{
        "subject": "Re: Draft", "sender_name": "Blaine Rout", "sender_email": "brout@cityofgreencastle.com",
        "message_type": "human", "importance": "high", "action_required": True,
        "keep_in_inbox": True, "confidence": 0.91, "reasoning": "Plan Commission feedback needed",
    }]
    section = append_run_summary(log_path, "2026-08-15 07:03", results, unmatched=[], errors=[])
    assert "Run 2026-08-15 07:03" in section
    assert "Blaine Rout" in section
    assert os.path.exists(log_path)
    with open(log_path) as f:
        assert "Blaine Rout" in f.read()


def test_append_run_summary_lists_unmatched_senders(tmp_path):
    log_path = str(tmp_path / "agent_log.md")
    unmatched = [{"sender_email": "jane@example.com", "sender_name": "Jane Somebody", "subject": "Volunteer schedule"}]
    section = append_run_summary(log_path, "2026-08-15 07:03", [], unmatched=unmatched, errors=[])
    assert "jane@example.com" in section
    assert "Volunteer schedule" in section


def test_update_latest_run_page_creates_then_reuses_page():
    client = MagicMock()
    client.create_child_page.return_value = {"id": "page-1"}
    conn = store.init_db(":memory:")
    config = MagicMock()
    config.notion_email_agent_parent_page_id = "parent-page-id"

    page_id_1 = update_latest_run_page(client, config, conn, "## Run 1\nsummary")
    assert page_id_1 == "page-1"
    client.create_child_page.assert_called_once()

    page_id_2 = update_latest_run_page(client, config, conn, "## Run 2\nsummary")
    assert page_id_2 == "page-1"
    client.create_child_page.assert_called_once()  # still only called once
    client.update_page.assert_called_once()
