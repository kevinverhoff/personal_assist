import pytest

from config import load_config, ConfigError


def test_load_config_reads_all_fields(full_env):
    cfg = load_config()
    assert cfg.google_client_id == "test-client-id"
    assert cfg.google_refresh_token == "test-refresh-token"
    assert cfg.notion_email_digests_data_source_id == "test-digests-ds"
    assert cfg.db_path == "./data/test.db"


def test_load_config_raises_on_missing_var(full_env, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        load_config()
