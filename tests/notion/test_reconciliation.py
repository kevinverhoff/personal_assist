from unittest.mock import MagicMock

from email_agent.notion.reconciliation import reconcile_sender
from email_agent.notion.people import PeopleCache


def _config():
    config = MagicMock()
    config.notion_people_data_source_id = "people-ds"
    config.notion_email_addresses_data_source_id = "emails-ds"
    return config


def test_known_sender_returns_known_no_writes():
    cache = PeopleCache(people_by_id={"p1": {"name": "Blaine Rout", "importance": None}}, email_to_person_id={"brout@cityofgreencastle.com": "p1"})
    client = MagicMock()
    result = reconcile_sender(client, _config(), cache, "brout@cityofgreencastle.com", "Blaine Rout", True, dry_run=False)
    assert result == {"action": "known", "person_id": "p1"}
    client.create_page.assert_not_called()


def test_name_match_attaches_email_when_not_dry_run():
    cache = PeopleCache(people_by_id={"p1": {"name": "Blaine Rout", "importance": None}}, email_to_person_id={})
    client = MagicMock()
    client.create_page.return_value = {"id": "email-page-1"}
    result = reconcile_sender(client, _config(), cache, "blaine.personal@gmail.com", "Blaine Rout", True, dry_run=False)
    assert result == {"action": "attached_email", "person_id": "p1", "logged_only": False}
    client.create_page.assert_called_once()
    call_kwargs = client.create_page.call_args
    assert call_kwargs.args[0] == "emails-ds"


def test_name_match_dry_run_does_not_call_notion():
    cache = PeopleCache(people_by_id={"p1": {"name": "Blaine Rout", "importance": None}}, email_to_person_id={})
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


def test_same_unknown_sender_twice_in_one_batch_does_not_duplicate():
    # Reproduces the real bug: a batch with two messages from the same new
    # sender must only create one Person + one Email, not two of each,
    # because reconcile_sender updates the cache in place after writing.
    cache = PeopleCache(people_by_id={}, email_to_person_id={})
    client = MagicMock()
    client.create_page.side_effect = [{"id": "person-new"}, {"id": "email-new"}]

    first = reconcile_sender(client, _config(), cache, "jeanne@example.com", "Jeanne Servais", True, dry_run=False)
    second = reconcile_sender(client, _config(), cache, "jeanne@example.com", "Jeanne Servais", True, dry_run=False)

    assert first == {"action": "created_person", "person_id": "person-new", "logged_only": False}
    assert second == {"action": "known", "person_id": "person-new"}
    assert client.create_page.call_count == 2  # only the first call wrote anything


def test_name_match_attach_updates_cache_so_repeat_sender_is_known():
    cache = PeopleCache(people_by_id={"p1": {"name": "Blaine Rout", "importance": None}}, email_to_person_id={})
    client = MagicMock()
    client.create_page.return_value = {"id": "email-page-1"}

    first = reconcile_sender(client, _config(), cache, "blaine.personal@gmail.com", "Blaine Rout", True, dry_run=False)
    second = reconcile_sender(client, _config(), cache, "blaine.personal@gmail.com", "Blaine Rout", True, dry_run=False)

    assert first == {"action": "attached_email", "person_id": "p1", "logged_only": False}
    assert second == {"action": "known", "person_id": "p1"}
    client.create_page.assert_called_once()  # only the first call wrote anything


def test_no_match_and_not_human_takes_no_action():
    cache = PeopleCache(people_by_id={}, email_to_person_id={})
    client = MagicMock()
    result = reconcile_sender(client, _config(), cache, "no-reply@service.com", "Service", False, dry_run=False)
    assert result == {"action": "no_action"}
    client.create_page.assert_not_called()
