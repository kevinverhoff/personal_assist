import os
import pytest


REQUIRED_ENV_VARS = {
    "GOOGLE_CLIENT_ID": "test-client-id",
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
    "GOOGLE_REFRESH_TOKEN": "test-refresh-token",
    "GEMINI_API_KEY": "test-gemini-key",
    "NOTION_TOKEN": "test-notion-token",
    "NOTION_PEOPLE_DATA_SOURCE_ID": "test-people-ds",
    "NOTION_ORGANIZATIONS_DATA_SOURCE_ID": "test-orgs-ds",
    "NOTION_AFFILIATIONS_DATA_SOURCE_ID": "test-affiliations-ds",
    "NOTION_EMAIL_ADDRESSES_DATA_SOURCE_ID": "test-emails-ds",
    "NOTION_EMAIL_DIGESTS_DATA_SOURCE_ID": "test-digests-ds",
    "NOTION_EMAIL_AGENT_PARENT_PAGE_ID": "test-parent-page-id",
    "DB_PATH": "./data/test.db",
    "LOG_PATH": "./logs/test.md",
}


@pytest.fixture
def full_env(monkeypatch):
    for key, value in REQUIRED_ENV_VARS.items():
        monkeypatch.setenv(key, value)
    return REQUIRED_ENV_VARS
