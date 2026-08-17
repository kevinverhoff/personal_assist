import os
from unittest.mock import MagicMock

import store
from agent_log import append_run_summary, update_latest_run_page


def _message(**overrides):
    base = {
        "gmail_message_id": "msg-1", "message_type": "human", "importance": "medium",
        "action_required": False, "matched_person_id": None, "subject": "Hi",
        "sender_name": "A Sender", "sender_email": "a@example.com",
    }
    base.update(overrides)
    return base


def test_append_run_summary_groups_known_people_first(tmp_path):
    log_path = str(tmp_path / "agent_log.md")
    known = _message(gmail_message_id="m1", matched_person_id="p1", message_type="human",
                      subject="Re: Draft", sender_name="Blaine Rout", sender_email="brout@cityofgreencastle.com")
    section = append_run_summary(log_path, "2026-08-15 07:03", [known], unmatched=[], errors=[])
    assert "### From people you know (1)" in section
    assert '- [human] "Re: Draft" — Blaine Rout (brout@cityofgreencastle.com)' in section
    assert os.path.exists(log_path)


def test_append_run_summary_puts_attention_worthy_unmatched_in_its_own_group(tmp_path):
    log_path = str(tmp_path / "agent_log.md")
    attention = _message(gmail_message_id="m2", matched_person_id=None, importance="high",
                          subject="Security alert", sender_name="Google", sender_email="no-reply@accounts.google.com")
    section = append_run_summary(log_path, "2026-08-15 07:03", [attention], unmatched=[], errors=[])
    assert "### May need your attention (1)" in section
    assert '- [human] "Security alert" — Google (no-reply@accounts.google.com)' in section


def test_append_run_summary_puts_routine_unmatched_in_everything_else(tmp_path):
    log_path = str(tmp_path / "agent_log.md")
    routine = _message(gmail_message_id="m3", matched_person_id=None, importance="low", action_required=False,
                        message_type="newsletter", subject="Weekly News", sender_name="X Weekly", sender_email="news@x.com")
    section = append_run_summary(log_path, "2026-08-15 07:03", [routine], unmatched=[], errors=[])
    assert "### Everything else (1)" in section
    assert '- [newsletter] "Weekly News" — X Weekly (news@x.com)' in section


def test_append_run_summary_lists_unmatched_senders(tmp_path):
    log_path = str(tmp_path / "agent_log.md")
    unmatched = [{"sender_email": "jane@example.com", "sender_name": "Jane Somebody", "subject": "Volunteer schedule"}]
    section = append_run_summary(log_path, "2026-08-15 07:03", [], unmatched=unmatched, errors=[])
    assert "jane@example.com" in section
    assert "Volunteer schedule" in section


def test_append_run_summary_lists_archived_messages(tmp_path):
    log_path = str(tmp_path / "agent_log.md")
    archived_msg = _message(gmail_message_id="m4", message_type="newsletter", subject="Old newsletter",
                             sender_name="Y News", sender_email="y@news.com")
    section = append_run_summary(log_path, "2026-08-15 07:03", [], unmatched=[], errors=[], archived=[archived_msg])
    assert "### Archived this run (1)" in section
    assert '- [newsletter] "Old newsletter" — Y News (y@news.com)' in section
    assert "1 archived" in section


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
    client.replace_page_content.assert_called_once_with("page-1", "## Run 2\nsummary")
