from unittest.mock import MagicMock

from reconciliation import reconcile_sender
from people_lookup import PeopleCache


def _config():
    config = MagicMock()
    config.notion_people_data_source_id = "people-ds"
    config.notion_email_addresses_data_source_id = "emails-ds"
    return config


def test_known_sender_returns_known_no_writes():
    cache = PeopleCache(people_by_id={"p1": "Blaine Rout"}, email_to_person_id={"brout@cityofgreencastle.com": "p1"})
    client = MagicMock()
    result = reconcile_sender(client, _config(), cache, "brout@cityofgreencastle.com", "Blaine Rout", True, dry_run=False)
    assert result == {"action": "known", "person_id": "p1"}
    client.create_page.assert_not_called()


def test_name_match_attaches_email_when_not_dry_run():
    cache = PeopleCache(people_by_id={"p1": "Blaine Rout"}, email_to_person_id={})
    client = MagicMock()
    client.create_page.return_value = {"id": "email-page-1"}
    result = reconcile_sender(client, _config(), cache, "blaine.personal@gmail.com", "Blaine Rout", True, dry_run=False)
    assert result == {"action": "attached_email", "person_id": "p1", "logged_only": False}
    client.create_page.assert_called_once()
    call_kwargs = client.create_page.call_args
    assert call_kwargs.args[0] == "emails-ds"


def test_name_match_dry_run_does_not_call_notion():
    cache = PeopleCache(people_by_id={"p1": "Blaine Rout"}, email_to_person_id={})
    client = MagicMock()
    result = reconcile_sender(client, _config(), cache, "blaine.personal@gmail.com", "Blaine Rout", True, dry_run=True)
    assert result == {"action": "attached_email", "person_id": "p1", "logged_only": True}
    client.create_page.assert_not_called()


def test_no_match_and_human_creates_person_and_email():
    cache = PeopleCache(people_by_id={}, email_to_person_id={})
    client = MagicMock()
    client.create_page.side_effect = [{"id": "person-new"}, {"id": "email-new"}]
    result = reconcile_sender(client, _config(), cache, "jane.somebody@example.com", "Jane Somebody", True, dry_run=False)
    assert result == {"action": "created_person", "person_id": "person-new", "logged_only": False}
    assert client.create_page.call_count == 2


def test_no_match_and_not_human_takes_no_action():
    cache = PeopleCache(people_by_id={}, email_to_person_id={})
    client = MagicMock()
    result = reconcile_sender(client, _config(), cache, "no-reply@service.com", "Service", False, dry_run=False)
    assert result == {"action": "no_action"}
    client.create_page.assert_not_called()
