from unittest.mock import MagicMock

from people_lookup import PeopleCache, normalize_name, NAME_MATCH_THRESHOLD


def _fake_client(people_pages, email_pages):
    client = MagicMock()

    def query_data_source(data_source_id, filter=None):
        if data_source_id == "people-ds":
            return people_pages
        if data_source_id == "emails-ds":
            return email_pages
        return []

    client.query_data_source.side_effect = query_data_source
    return client


def _fake_config():
    config = MagicMock()
    config.notion_people_data_source_id = "people-ds"
    config.notion_email_addresses_data_source_id = "emails-ds"
    return config


def test_normalize_name_folds_case_and_whitespace():
    assert normalize_name("  Blaine   Rout ") == "blaine rout"


def test_match_by_email_exact():
    people = [{"id": "person-1", "properties": {"Name": {"title": [{"plain_text": "Blaine Rout"}]}}}]
    emails = [{"properties": {
        "Email": {"email": "brout@cityofgreencastle.com"},
        "Person": {"relation": [{"id": "person-1"}]},
    }}]
    cache = PeopleCache.load(_fake_client(people, emails), _fake_config())
    match = cache.match_by_email("brout@cityofgreencastle.com")
    assert match == {"person_id": "person-1", "person_name": "Blaine Rout"}


def test_match_by_email_no_match_returns_none():
    cache = PeopleCache.load(_fake_client([], []), _fake_config())
    assert cache.match_by_email("nobody@example.com") is None


def test_match_by_name_exact_returns_high_score():
    people = [{"id": "person-1", "properties": {"Name": {"title": [{"plain_text": "Blaine Rout"}]}}}]
    cache = PeopleCache.load(_fake_client(people, []), _fake_config())
    match = cache.match_by_name("Blaine Rout")
    assert match["person_id"] == "person-1"
    assert match["score"] >= NAME_MATCH_THRESHOLD


def test_match_by_name_weak_match_returns_none():
    people = [{"id": "person-1", "properties": {"Name": {"title": [{"plain_text": "Blaine Rout"}]}}}]
    cache = PeopleCache.load(_fake_client(people, []), _fake_config())
    assert cache.match_by_name("Someone Completely Different") is None
