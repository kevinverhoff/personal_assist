# Email Intelligence Agent Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, read-only Python pipeline that ingests personal Gmail inbox messages, classifies each along 7 independent dimensions via Gemini, reconciles senders against the existing Notion People/Organizations/Affiliations/Email Addresses databases, stores everything in local SQLite, and produces a human-readable notepad log plus daily/weekly Notion digests and a feedback-capture CLI — with zero Gmail mutations anywhere in the codebase.

**Architecture:** A set of small, single-responsibility Python modules at the repo root (matching the existing `notion-asana` repo's flat, procedural style) wired together by three thin entrypoints — `main.py` (ingestion), `digest.py` (daily/weekly rollup), `feedback.py` (correction capture) — sharing a local SQLite store and a Notion REST client. Every external call (Gmail, Gemini, Notion) is tested twice: once with a unit test against a mock, once with a documented manual step against your real credentials, per your explicit request to test with real data as we build.

**Tech Stack:** Python 3.11+, `google-auth`/`google-auth-oauthlib`/`google-api-python-client` (Gmail), `google-genai` (Gemini), `requests` (Notion REST), stdlib `sqlite3`, `python-dotenv`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-08-14-email-intelligence-agent-design.md`

## Global Constraints

- Never call any Gmail-mutating API in any task: no archive, delete, label, move, mark-read/unread, send, or filter changes. This codebase only ever calls `users.history.list` / `users.messages.get`.
- Gmail fetch is always scoped to `in:inbox` — never the whole mailbox.
- `keep_in_inbox` defaults to `true` whenever classification fails or confidence is low. Uncertainty always resolves toward not touching the inbox.
- Every auto-created or auto-modified Notion record (Person, Email Address, and — in a future phase — Organization/Affiliation) is written with `Status`/`Confidence` = `Needs Review`/`Inferred - needs review`, never `Confirmed`. Nothing this codebase writes is ever presented as settled fact.
- Name-based sender matching only auto-writes to Notion above a defined high-confidence threshold (`NAME_MATCH_THRESHOLD = 0.92`, see Task 5); weaker matches are logged only, never written.
- Signature/domain-based Organization/Affiliation inference is **out of scope for this plan** (deferred to spec's v1.1) — auto-create from an unmatched sender produces a Person + Email Address only.
- Digest counts (§6c of the spec) are always computed deterministically in Python before any Gemini phrasing call — Gemini is only ever given pre-computed numbers to phrase, never asked to count.
- No GitHub Actions, no Cloudflare D1 in this plan — Phase 1 is entirely local (manual invocation, local SQLite, local files). That's a Phase 1b plan, not this one.

---

## File Structure

```
personal_assist/
  requirements.txt
  config.py                # env var loading/validation
  gmail_auth_setup.py      # one-time interactive OAuth consent script
  gmail_client.py          # Gmail API: refresh token -> fetch messages
  signals.py               # deterministic header/sender signal extraction
  notion_client.py         # thin Notion REST wrapper (query/create/update)
  people_lookup.py         # in-memory People/Org cache + read-only matching
  reconciliation.py        # §6b write-back: attach email / create person
  classifier.py            # Gemini structured classification call
  store.py                 # local SQLite: messages, sync_state, run_log, feedback
  agent_log.py             # notepad log + Notion "Latest Run" page
  digest.py                # daily/weekly digest generation + Notion write
  feedback.py              # feedback-capture CLI
  main.py                  # ingestion entrypoint, wires everything together
  tests/
    conftest.py
    test_config.py
    test_signals.py
    test_store.py
    test_notion_client.py
    test_people_lookup.py
    test_reconciliation.py
    test_classifier.py
    test_gmail_client.py
    test_agent_log.py
    test_digest.py
    test_feedback.py
    test_main.py
  data/                    # gitignored, DB_PATH default parent
  logs/                    # gitignored, LOG_PATH default parent
```

---

### Task 1: Project scaffolding and config loader

**Files:**
- Create: `requirements.txt`
- Create: `config.py`
- Modify: `.gitignore` (add `data/` and `logs/`)
- Test: `tests/test_config.py`
- Test: `tests/conftest.py`

**Interfaces:**
- Produces: `config.load_config() -> Config`, `Config` dataclass with fields `google_client_id: str`, `google_client_secret: str`, `google_refresh_token: str`, `gemini_api_key: str`, `notion_token: str`, `notion_people_data_source_id: str`, `notion_organizations_data_source_id: str`, `notion_affiliations_data_source_id: str`, `notion_email_addresses_data_source_id: str`, `notion_email_digests_data_source_id: str`, `db_path: str`, `log_path: str`; `config.ConfigError(Exception)`.

- [ ] **Step 1: Create `requirements.txt`**

```
python-dotenv>=1.0.1
google-auth>=2.35.0
google-auth-oauthlib>=1.2.1
google-api-python-client>=2.140.0
google-genai>=1.2.0
requests>=2.32.0
pytest>=8.3.0
```

- [ ] **Step 2: Install dependencies**

Run: `pip install -r requirements.txt`
Expected: all packages install with no errors.

- [ ] **Step 3: Write the failing test**

Create `tests/conftest.py`:

```python
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
    "DB_PATH": "./data/test.db",
    "LOG_PATH": "./logs/test.md",
}


@pytest.fixture
def full_env(monkeypatch):
    for key, value in REQUIRED_ENV_VARS.items():
        monkeypatch.setenv(key, value)
    return REQUIRED_ENV_VARS
```

Create `tests/test_config.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 5: Write minimal implementation**

Create `config.py`:

```python
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

_REQUIRED_VARS = [
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN",
    "GEMINI_API_KEY",
    "NOTION_TOKEN",
    "NOTION_PEOPLE_DATA_SOURCE_ID",
    "NOTION_ORGANIZATIONS_DATA_SOURCE_ID",
    "NOTION_AFFILIATIONS_DATA_SOURCE_ID",
    "NOTION_EMAIL_ADDRESSES_DATA_SOURCE_ID",
    "NOTION_EMAIL_DIGESTS_DATA_SOURCE_ID",
    "DB_PATH",
    "LOG_PATH",
]


class ConfigError(Exception):
    pass


@dataclass
class Config:
    google_client_id: str
    google_client_secret: str
    google_refresh_token: str
    gemini_api_key: str
    notion_token: str
    notion_people_data_source_id: str
    notion_organizations_data_source_id: str
    notion_affiliations_data_source_id: str
    notion_email_addresses_data_source_id: str
    notion_email_digests_data_source_id: str
    db_path: str
    log_path: str


def load_config() -> Config:
    missing = [name for name in _REQUIRED_VARS if not os.environ.get(name)]
    if missing:
        raise ConfigError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            f"Copy env.example to .env and fill in real values."
        )
    return Config(
        google_client_id=os.environ["GOOGLE_CLIENT_ID"],
        google_client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        google_refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        notion_token=os.environ["NOTION_TOKEN"],
        notion_people_data_source_id=os.environ["NOTION_PEOPLE_DATA_SOURCE_ID"],
        notion_organizations_data_source_id=os.environ["NOTION_ORGANIZATIONS_DATA_SOURCE_ID"],
        notion_affiliations_data_source_id=os.environ["NOTION_AFFILIATIONS_DATA_SOURCE_ID"],
        notion_email_addresses_data_source_id=os.environ["NOTION_EMAIL_ADDRESSES_DATA_SOURCE_ID"],
        notion_email_digests_data_source_id=os.environ["NOTION_EMAIL_DIGESTS_DATA_SOURCE_ID"],
        db_path=os.environ["DB_PATH"],
        log_path=os.environ["LOG_PATH"],
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: 2 passed

- [ ] **Step 7: Add `data/` and `logs/` to `.gitignore`**

Append to `.gitignore`:

```
# Email Intelligence Agent local state
/data/
/logs/
```

- [ ] **Step 8: Commit**

```bash
git add requirements.txt config.py tests/conftest.py tests/test_config.py .gitignore
git commit -m "Add config loader with required-var validation"
```

---

### Task 2: Local SQLite store

**Files:**
- Create: `store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `store.init_db(db_path: str) -> sqlite3.Connection`, `store.upsert_message(conn, message: dict) -> None`, `store.get_sync_state(conn) -> dict | None`, `store.set_sync_state(conn, last_history_id: str, last_run_at: str) -> None`, `store.insert_run_log(conn, run_at: str, messages_processed: int, status: str, errors: str | None) -> None`, `store.insert_feedback(conn, gmail_message_id: str, original_classification: str, corrected_fields: str, note: str, corrected_at: str) -> None`, `store.get_messages_in_window(conn, start_iso: str, end_iso: str) -> list[dict]`, `store.get_recent_messages(conn, limit: int) -> list[dict]`. `message` dict keys match the `messages` table columns exactly (see below).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_store.py`:

```python
import store


def test_init_db_creates_tables():
    conn = store.init_db(":memory:")
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    assert {"messages", "sync_state", "run_log", "feedback"} <= tables


def test_upsert_message_inserts_then_updates():
    conn = store.init_db(":memory:")
    message = {
        "gmail_message_id": "msg-1",
        "thread_id": "thread-1",
        "sender_email": "a@example.com",
        "sender_name": "A Sender",
        "subject": "Hello",
        "received_at": "2026-08-15T07:00:00Z",
        "snippet": "hi there",
        "message_type": "human",
        "importance": "high",
        "action_required": 1,
        "keep_in_inbox": 1,
        "digest_worthy": 0,
        "confidence": 0.9,
        "reasoning": "looks like a real person",
        "person_org_signal": None,
        "matched_person_id": None,
        "matched_org_ids": None,
        "processed_at": "2026-08-15T07:00:01Z",
    }
    store.upsert_message(conn, message)
    rows = conn.execute("SELECT subject FROM messages WHERE gmail_message_id = 'msg-1'").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Hello"

    message["subject"] = "Updated Subject"
    store.upsert_message(conn, message)
    rows = conn.execute("SELECT subject FROM messages WHERE gmail_message_id = 'msg-1'").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Updated Subject"


def test_sync_state_round_trip():
    conn = store.init_db(":memory:")
    assert store.get_sync_state(conn) is None
    store.set_sync_state(conn, last_history_id="12345", last_run_at="2026-08-15T07:00:00Z")
    state = store.get_sync_state(conn)
    assert state["last_history_id"] == "12345"
    store.set_sync_state(conn, last_history_id="67890", last_run_at="2026-08-15T08:00:00Z")
    state = store.get_sync_state(conn)
    assert state["last_history_id"] == "67890"


def test_insert_run_log():
    conn = store.init_db(":memory:")
    store.insert_run_log(conn, run_at="2026-08-15T07:00:00Z", messages_processed=5, status="ok", errors=None)
    rows = conn.execute("SELECT status, messages_processed FROM run_log").fetchall()
    assert rows == [("ok", 5)]


def test_insert_and_fetch_feedback():
    conn = store.init_db(":memory:")
    store.insert_feedback(
        conn,
        gmail_message_id="msg-1",
        original_classification='{"importance": "low"}',
        corrected_fields='{"importance": "high"}',
        note="this was actually urgent",
        corrected_at="2026-08-15T09:00:00Z",
    )
    rows = conn.execute("SELECT gmail_message_id, note FROM feedback").fetchall()
    assert rows == [("msg-1", "this was actually urgent")]


def test_get_messages_in_window_filters_by_date():
    conn = store.init_db(":memory:")
    for i, received_at in enumerate(["2026-08-14T07:00:00Z", "2026-08-15T07:00:00Z", "2026-08-16T07:00:00Z"]):
        store.upsert_message(conn, {
            "gmail_message_id": f"msg-{i}", "thread_id": "t", "sender_email": "a@example.com",
            "sender_name": "A", "subject": "s", "received_at": received_at, "snippet": "",
            "message_type": "newsletter", "importance": "low", "action_required": 0,
            "keep_in_inbox": 1, "digest_worthy": 1, "confidence": 0.9, "reasoning": "r",
            "person_org_signal": None, "matched_person_id": None, "matched_org_ids": None,
            "processed_at": received_at,
        })
    results = store.get_messages_in_window(conn, "2026-08-15T00:00:00Z", "2026-08-15T23:59:59Z")
    assert [m["gmail_message_id"] for m in results] == ["msg-1"]


def test_get_recent_messages_limit_and_order():
    conn = store.init_db(":memory:")
    for i, received_at in enumerate(["2026-08-14T07:00:00Z", "2026-08-15T07:00:00Z", "2026-08-16T07:00:00Z"]):
        store.upsert_message(conn, {
            "gmail_message_id": f"msg-{i}", "thread_id": "t", "sender_email": "a@example.com",
            "sender_name": "A", "subject": f"subject-{i}", "received_at": received_at, "snippet": "",
            "message_type": "newsletter", "importance": "low", "action_required": 0,
            "keep_in_inbox": 1, "digest_worthy": 1, "confidence": 0.9, "reasoning": "r",
            "person_org_signal": None, "matched_person_id": None, "matched_org_ids": None,
            "processed_at": received_at,
        })
    results = store.get_recent_messages(conn, limit=2)
    assert [m["subject"] for m in results] == ["subject-2", "subject-1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'store'`

- [ ] **Step 3: Write minimal implementation**

Create `store.py`:

```python
import os
import sqlite3


_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  gmail_message_id TEXT PRIMARY KEY,
  thread_id TEXT,
  sender_email TEXT,
  sender_name TEXT,
  subject TEXT,
  received_at TEXT,
  snippet TEXT,
  message_type TEXT,
  importance TEXT,
  action_required INTEGER,
  keep_in_inbox INTEGER,
  digest_worthy INTEGER,
  confidence REAL,
  reasoning TEXT,
  person_org_signal TEXT,
  matched_person_id TEXT,
  matched_org_ids TEXT,
  processed_at TEXT
);

CREATE TABLE IF NOT EXISTS sync_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  last_history_id TEXT,
  last_run_at TEXT
);

CREATE TABLE IF NOT EXISTS run_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at TEXT,
  messages_processed INTEGER,
  status TEXT,
  errors TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  gmail_message_id TEXT,
  original_classification TEXT,
  corrected_fields TEXT,
  note TEXT,
  corrected_at TEXT
);
"""

_MESSAGE_COLUMNS = [
    "gmail_message_id", "thread_id", "sender_email", "sender_name", "subject",
    "received_at", "snippet", "message_type", "importance", "action_required",
    "keep_in_inbox", "digest_worthy", "confidence", "reasoning",
    "person_org_signal", "matched_person_id", "matched_org_ids", "processed_at",
]


def init_db(db_path: str) -> sqlite3.Connection:
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def upsert_message(conn: sqlite3.Connection, message: dict) -> None:
    placeholders = ", ".join("?" for _ in _MESSAGE_COLUMNS)
    columns = ", ".join(_MESSAGE_COLUMNS)
    update_clause = ", ".join(f"{col} = excluded.{col}" for col in _MESSAGE_COLUMNS if col != "gmail_message_id")
    conn.execute(
        f"INSERT INTO messages ({columns}) VALUES ({placeholders}) "
        f"ON CONFLICT(gmail_message_id) DO UPDATE SET {update_clause}",
        [message[col] for col in _MESSAGE_COLUMNS],
    )
    conn.commit()


def get_sync_state(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT last_history_id, last_run_at FROM sync_state WHERE id = 1").fetchone()
    return dict(row) if row else None


def set_sync_state(conn: sqlite3.Connection, last_history_id: str, last_run_at: str) -> None:
    conn.execute(
        "INSERT INTO sync_state (id, last_history_id, last_run_at) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET last_history_id = excluded.last_history_id, "
        "last_run_at = excluded.last_run_at",
        (last_history_id, last_run_at),
    )
    conn.commit()


def insert_run_log(conn: sqlite3.Connection, run_at: str, messages_processed: int, status: str, errors: str | None) -> None:
    conn.execute(
        "INSERT INTO run_log (run_at, messages_processed, status, errors) VALUES (?, ?, ?, ?)",
        (run_at, messages_processed, status, errors),
    )
    conn.commit()


def insert_feedback(conn: sqlite3.Connection, gmail_message_id: str, original_classification: str,
                     corrected_fields: str, note: str, corrected_at: str) -> None:
    conn.execute(
        "INSERT INTO feedback (gmail_message_id, original_classification, corrected_fields, note, corrected_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (gmail_message_id, original_classification, corrected_fields, note, corrected_at),
    )
    conn.commit()


def get_messages_in_window(conn: sqlite3.Connection, start_iso: str, end_iso: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM messages WHERE received_at >= ? AND received_at <= ? ORDER BY received_at",
        (start_iso, end_iso),
    ).fetchall()
    return [dict(row) for row in rows]


def get_recent_messages(conn: sqlite3.Connection, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM messages ORDER BY received_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(row) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_store.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add store.py tests/test_store.py
git commit -m "Add local SQLite store with idempotent message upsert"
```

---

### Task 3: Deterministic signal extraction

**Files:**
- Create: `signals.py`
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `signals.extract_signals(headers: dict[str, str], sender_email: str) -> dict` returning `{"has_list_unsubscribe": bool, "is_bulk_precedence": bool, "sender_domain": str, "looks_automated": bool}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_signals.py`:

```python
from signals import extract_signals


def test_detects_list_unsubscribe():
    result = extract_signals({"List-Unsubscribe": "<mailto:unsub@x.com>"}, "news@x.com")
    assert result["has_list_unsubscribe"] is True


def test_no_list_unsubscribe():
    result = extract_signals({}, "friend@example.com")
    assert result["has_list_unsubscribe"] is False


def test_detects_bulk_precedence():
    result = extract_signals({"Precedence": "bulk"}, "news@x.com")
    assert result["is_bulk_precedence"] is True


def test_extracts_sender_domain():
    result = extract_signals({}, "person@cityofgreencastle.com")
    assert result["sender_domain"] == "cityofgreencastle.com"


def test_looks_automated_for_noreply():
    result = extract_signals({}, "no-reply@service.com")
    assert result["looks_automated"] is True


def test_does_not_look_automated_for_real_name_style_address():
    result = extract_signals({}, "jane.smith@example.com")
    assert result["looks_automated"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_signals.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'signals'`

- [ ] **Step 3: Write minimal implementation**

Create `signals.py`:

```python
import re

_AUTOMATED_PATTERNS = [
    r"no-?reply",
    r"do-?not-?reply",
    r"^notifications?@",
    r"^mailer@",
    r"^automated@",
]


def _has_list_unsubscribe(headers: dict) -> bool:
    return any(key.lower() == "list-unsubscribe" for key in headers)


def _is_bulk_precedence(headers: dict) -> bool:
    for key, value in headers.items():
        if key.lower() == "precedence" and value.strip().lower() in ("bulk", "list"):
            return True
    return False


def _sender_domain(sender_email: str) -> str:
    return sender_email.split("@")[-1].lower() if "@" in sender_email else ""


def _looks_automated(sender_email: str) -> bool:
    local_part = sender_email.split("@")[0].lower()
    return any(re.search(pattern, local_part) for pattern in _AUTOMATED_PATTERNS)


def extract_signals(headers: dict[str, str], sender_email: str) -> dict:
    return {
        "has_list_unsubscribe": _has_list_unsubscribe(headers),
        "is_bulk_precedence": _is_bulk_precedence(headers),
        "sender_domain": _sender_domain(sender_email),
        "looks_automated": _looks_automated(sender_email),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_signals.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add signals.py tests/test_signals.py
git commit -m "Add deterministic header/sender signal extraction"
```

---

### Task 4: Notion REST client

**Files:**
- Create: `notion_client.py`
- Test: `tests/test_notion_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (takes a raw token string).
- Produces: `notion_client.NotionClient(token: str)` with methods `.query_data_source(data_source_id: str, filter: dict | None = None) -> list[dict]`, `.create_page(data_source_id: str, properties: dict, content: str | None = None) -> dict`, `.update_page(page_id: str, properties: dict | None = None) -> dict`. Every returned page dict has at least `{"id": str, "properties": dict}`.

**Note on the Notion API surface:** this targets Notion's current data-source-based REST API (`POST https://api.notion.com/v1/data_sources/{id}/query`, page creation with `parent: {"type": "data_source_id", "data_source_id": ...}`), matching the multi-source-database model these Notion databases were already built on. If the real API responds with a 404 or a different expected shape during Step 6's manual verification, check `https://developers.notion.com/reference` for the current endpoint path and adjust `_BASE_URL`/`Notion-Version` accordingly — that's exactly what the manual check is for.

- [ ] **Step 1: Write the failing tests (mocked HTTP)**

Create `tests/test_notion_client.py`:

```python
from unittest.mock import MagicMock, patch

from notion_client import NotionClient


def _mock_response(json_data, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status = MagicMock()
    return response


@patch("notion_client.requests.post")
def test_query_data_source_sends_correct_request(mock_post):
    mock_post.return_value = _mock_response({"results": [{"id": "page-1", "properties": {}}], "has_more": False})
    client = NotionClient(token="secret_abc")
    results = client.query_data_source("ds-123", filter={"property": "Email", "email": {"equals": "a@x.com"}})

    assert results == [{"id": "page-1", "properties": {}}]
    called_url = mock_post.call_args.args[0]
    assert "ds-123" in called_url
    called_headers = mock_post.call_args.kwargs["headers"]
    assert called_headers["Authorization"] == "Bearer secret_abc"
    assert "Notion-Version" in called_headers


@patch("notion_client.requests.post")
def test_query_data_source_paginates(mock_post):
    mock_post.side_effect = [
        _mock_response({"results": [{"id": "p1", "properties": {}}], "has_more": True, "next_cursor": "cur1"}),
        _mock_response({"results": [{"id": "p2", "properties": {}}], "has_more": False}),
    ]
    client = NotionClient(token="secret_abc")
    results = client.query_data_source("ds-123")
    assert [r["id"] for r in results] == ["p1", "p2"]
    assert mock_post.call_count == 2


@patch("notion_client.requests.post")
def test_create_page_sends_parent_and_properties(mock_post):
    mock_post.return_value = _mock_response({"id": "new-page", "properties": {"Name": {}}})
    client = NotionClient(token="secret_abc")
    result = client.create_page("ds-123", properties={"Name": {"title": [{"text": {"content": "Jane"}}]}})
    assert result["id"] == "new-page"
    payload = mock_post.call_args.kwargs["json"]
    assert payload["parent"] == {"type": "data_source_id", "data_source_id": "ds-123"}
    assert payload["properties"]["Name"]["title"][0]["text"]["content"] == "Jane"


@patch("notion_client.requests.patch")
def test_update_page_sends_properties(mock_patch):
    mock_patch.return_value = _mock_response({"id": "page-1", "properties": {}})
    client = NotionClient(token="secret_abc")
    result = client.update_page("page-1", properties={"Status": {"select": {"name": "Needs Review"}}})
    assert result["id"] == "page-1"
    payload = mock_patch.call_args.kwargs["json"]
    assert payload["properties"]["Status"]["select"]["name"] == "Needs Review"


@patch("notion_client.requests.post")
def test_create_standalone_page_uses_workspace_parent(mock_post):
    mock_post.return_value = _mock_response({"id": "standalone-page-1"})
    client = NotionClient(token="secret_abc")
    result = client.create_standalone_page("Email Agent — Latest Run", content="hello")
    assert result["id"] == "standalone-page-1"
    payload = mock_post.call_args.kwargs["json"]
    assert payload["parent"] == {"type": "workspace", "workspace": True}
    assert payload["properties"]["title"]["title"][0]["text"]["content"] == "Email Agent — Latest Run"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_notion_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'notion_client'`

- [ ] **Step 3: Write minimal implementation**

Create `notion_client.py`:

```python
import requests

_BASE_URL = "https://api.notion.com/v1"
_NOTION_VERSION = "2025-09-03"


class NotionClient:
    def __init__(self, token: str):
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": _NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def query_data_source(self, data_source_id: str, filter: dict | None = None) -> list[dict]:
        results: list[dict] = []
        cursor = None
        while True:
            payload: dict = {}
            if filter:
                payload["filter"] = filter
            if cursor:
                payload["start_cursor"] = cursor
            response = requests.post(
                f"{_BASE_URL}/data_sources/{data_source_id}/query",
                headers=self._headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            results.extend(data["results"])
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return results

    def create_page(self, data_source_id: str, properties: dict, content: str | None = None) -> dict:
        payload: dict = {
            "parent": {"type": "data_source_id", "data_source_id": data_source_id},
            "properties": properties,
        }
        if content:
            payload["children"] = [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]},
                }
            ]
        response = requests.post(f"{_BASE_URL}/pages", headers=self._headers, json=payload)
        response.raise_for_status()
        return response.json()

    def update_page(self, page_id: str, properties: dict | None = None) -> dict:
        payload: dict = {}
        if properties:
            payload["properties"] = properties
        response = requests.patch(f"{_BASE_URL}/pages/{page_id}", headers=self._headers, json=payload)
        response.raise_for_status()
        return response.json()

    def create_standalone_page(self, title: str, content: str | None = None) -> dict:
        payload: dict = {
            "parent": {"type": "workspace", "workspace": True},
            "properties": {"title": {"title": [{"text": {"content": title}}]}},
        }
        if content:
            payload["children"] = [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]},
                }
            ]
        response = requests.post(f"{_BASE_URL}/pages", headers=self._headers, json=payload)
        response.raise_for_status()
        return response.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_notion_client.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add notion_client.py tests/test_notion_client.py
git commit -m "Add Notion REST client with pagination"
```

- [ ] **Step 6: Manual verification against real Notion**

Run a quick interactive check (adjust the data source id to your real `NOTION_PEOPLE_DATA_SOURCE_ID`):

```bash
python -c "
from config import load_config
from notion_client import NotionClient
cfg = load_config()
client = NotionClient(cfg.notion_token)
people = client.query_data_source(cfg.notion_people_data_source_id)
print(f'Found {len(people)} people')
print(people[0]['properties'].get('Name'))
"
```

Expected: prints `Found 32 people` (or more, if you've added any) and the first person's Name property. If you get a 404 or a shape error, check `https://developers.notion.com/reference/query-a-data-source` for the current endpoint and fix `notion_client.py` before proceeding — every later task depends on this working against your real workspace.

---

### Task 5: People/Organizations in-memory cache and matching

**Files:**
- Create: `people_lookup.py`
- Test: `tests/test_people_lookup.py`

**Interfaces:**
- Consumes: `notion_client.NotionClient` from Task 4.
- Produces: `people_lookup.PeopleCache.load(client: NotionClient, config: Config) -> PeopleCache`; `PeopleCache.match_by_email(email: str) -> dict | None` (returns `{"person_id": str, "person_name": str}` or `None`); `PeopleCache.match_by_name(display_name: str) -> dict | None` (returns `{"person_id": str, "person_name": str, "score": float}` only when `score >= NAME_MATCH_THRESHOLD`, else `None`); `people_lookup.NAME_MATCH_THRESHOLD = 0.92`; `people_lookup.normalize_name(name: str) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_people_lookup.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_people_lookup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'people_lookup'`

- [ ] **Step 3: Write minimal implementation**

Create `people_lookup.py`:

```python
import difflib
import re
from dataclasses import dataclass, field

NAME_MATCH_THRESHOLD = 0.92


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _extract_title(properties: dict, prop_name: str) -> str:
    prop = properties.get(prop_name, {})
    title_parts = prop.get("title", [])
    return "".join(part.get("plain_text", "") for part in title_parts)


@dataclass
class PeopleCache:
    people_by_id: dict = field(default_factory=dict)   # person_id -> name
    email_to_person_id: dict = field(default_factory=dict)  # normalized email -> person_id

    @classmethod
    def load(cls, client, config) -> "PeopleCache":
        people_by_id = {}
        for page in client.query_data_source(config.notion_people_data_source_id):
            name = _extract_title(page["properties"], "Name")
            people_by_id[page["id"]] = name

        email_to_person_id = {}
        for page in client.query_data_source(config.notion_email_addresses_data_source_id):
            props = page["properties"]
            email = (props.get("Email", {}) or {}).get("email")
            relation = (props.get("Person", {}) or {}).get("relation", [])
            if email and relation:
                email_to_person_id[email.strip().lower()] = relation[0]["id"]

        return cls(people_by_id=people_by_id, email_to_person_id=email_to_person_id)

    def match_by_email(self, email: str) -> dict | None:
        person_id = self.email_to_person_id.get(email.strip().lower())
        if not person_id:
            return None
        return {"person_id": person_id, "person_name": self.people_by_id[person_id]}

    def match_by_name(self, display_name: str) -> dict | None:
        if not display_name:
            return None
        target = normalize_name(display_name)
        best_id, best_score = None, 0.0
        for person_id, name in self.people_by_id.items():
            score = difflib.SequenceMatcher(a=target, b=normalize_name(name)).ratio()
            if score > best_score:
                best_id, best_score = person_id, score
        if best_id and best_score >= NAME_MATCH_THRESHOLD:
            return {"person_id": best_id, "person_name": self.people_by_id[best_id], "score": best_score}
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_people_lookup.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add people_lookup.py tests/test_people_lookup.py
git commit -m "Add in-memory People cache with email and name matching"
```

- [ ] **Step 6: Manual verification against real Notion**

```bash
python -c "
from config import load_config
from notion_client import NotionClient
from people_lookup import PeopleCache
cfg = load_config()
cache = PeopleCache.load(NotionClient(cfg.notion_token), cfg)
print(f'{len(cache.people_by_id)} people loaded, {len(cache.email_to_person_id)} known emails')
print(cache.match_by_email('brout@cityofgreencastle.com'))
print(cache.match_by_name('blaine rout'))
"
```

Expected: `32 people loaded, 5 known emails`, then a match dict for Blaine Rout from both the email and the (lowercased, slightly different casing) name lookup.

---

### Task 6: Reconciliation write-back

**Files:**
- Create: `reconciliation.py`
- Test: `tests/test_reconciliation.py`

**Interfaces:**
- Consumes: `notion_client.NotionClient` (Task 4), `people_lookup.PeopleCache` (Task 5).
- Produces: `reconciliation.reconcile_sender(client, config, cache, sender_email: str, sender_name: str, is_human: bool, dry_run: bool) -> dict` returning one of `{"action": "known", "person_id": str}`, `{"action": "attached_email", "person_id": str, "logged_only": bool}`, `{"action": "created_person", "person_id": str | None, "logged_only": bool}`, `{"action": "no_action"}` (for automated senders, or ambiguous name matches below threshold).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reconciliation.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reconciliation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reconciliation'`

- [ ] **Step 3: Write minimal implementation**

Create `reconciliation.py`:

```python
def _person_page_properties(name: str) -> dict:
    return {
        "Name": {"title": [{"text": {"content": name}}]},
        "Status": {"select": {"name": "Needs Review"}},
        "Active": {"checkbox": True},
    }


def _email_page_properties(address: str, person_id: str) -> dict:
    return {
        "Address": {"title": [{"text": {"content": address}}]},
        "Email": {"email": address},
        "Person": {"relation": [{"id": person_id}]},
        "Confidence": {"select": {"name": "Inferred - needs review"}},
    }


def reconcile_sender(client, config, cache, sender_email: str, sender_name: str, is_human: bool, dry_run: bool) -> dict:
    existing = cache.match_by_email(sender_email)
    if existing:
        return {"action": "known", "person_id": existing["person_id"]}

    name_match = cache.match_by_name(sender_name)
    if name_match:
        if dry_run:
            return {"action": "attached_email", "person_id": name_match["person_id"], "logged_only": True}
        client.create_page(
            config.notion_email_addresses_data_source_id,
            _email_page_properties(sender_email, name_match["person_id"]),
        )
        return {"action": "attached_email", "person_id": name_match["person_id"], "logged_only": False}

    if not is_human:
        return {"action": "no_action"}

    if dry_run:
        return {"action": "created_person", "person_id": None, "logged_only": True}

    person_page = client.create_page(config.notion_people_data_source_id, _person_page_properties(sender_name))
    client.create_page(
        config.notion_email_addresses_data_source_id,
        _email_page_properties(sender_email, person_page["id"]),
    )
    return {"action": "created_person", "person_id": person_page["id"], "logged_only": False}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reconciliation.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add reconciliation.py tests/test_reconciliation.py
git commit -m "Add sender-to-Person reconciliation with dry-run support"
```

- [ ] **Step 6: Manual verification against real Notion (dry-run first)**

```bash
python -c "
from config import load_config
from notion_client import NotionClient
from people_lookup import PeopleCache
from reconciliation import reconcile_sender
cfg = load_config()
client = NotionClient(cfg.notion_token)
cache = PeopleCache.load(client, cfg)
result = reconcile_sender(client, cfg, cache, 'test.person@example.com', 'Test Person', True, dry_run=True)
print(result)
"
```

Expected: `{'action': 'created_person', 'person_id': None, 'logged_only': True}` and **no new page in Notion** — confirm by checking the People database. Then run the same command with `dry_run=False` once to confirm a real "Test Person" (`Status: Needs Review`) and email address get created — and delete that test record from Notion afterward since it's not a real contact.

---

### Task 7: Gemini classifier

**Files:**
- Create: `classifier.py`
- Test: `tests/test_classifier.py`

**Interfaces:**
- Consumes: nothing from earlier tasks except a `Config` (for the API key).
- Produces: `classifier.classify_message(client, subject: str, snippet: str, body: str, signals: dict, person_match: dict | None) -> dict` returning the 7-field dict from spec §6 plus `reasoning`: `{"message_type": str, "importance": str, "action_required": bool, "keep_in_inbox": bool, "digest_worthy": bool, "person_org_signal": str | None, "confidence": float, "reasoning": str}`. `classifier.make_client(api_key: str)` returns a `google.genai.Client`. On any exception during the Gemini call, `classify_message` returns the safe-default dict (`keep_in_inbox=True`, `message_type="uncertain"`, `confidence=0.0`, `reasoning=str(error)`) rather than raising.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_classifier.py`:

```python
import json
from unittest.mock import MagicMock

from classifier import classify_message


def _fake_client_returning(payload: dict):
    client = MagicMock()
    response = MagicMock()
    response.text = json.dumps(payload)
    client.models.generate_content.return_value = response
    return client


def test_classify_message_returns_parsed_schema():
    payload = {
        "message_type": "human", "importance": "high", "action_required": True,
        "keep_in_inbox": True, "digest_worthy": False, "person_org_signal": None,
        "confidence": 0.91, "reasoning": "Plan Commission asking for feedback",
    }
    client = _fake_client_returning(payload)
    result = classify_message(client, "Re: Draft", "please review", "please review by Friday", {}, None)
    assert result == payload


def test_classify_message_falls_back_safely_on_exception():
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("API down")
    result = classify_message(client, "subject", "snippet", "body", {}, None)
    assert result["keep_in_inbox"] is True
    assert result["message_type"] == "uncertain"
    assert result["confidence"] == 0.0
    assert "API down" in result["reasoning"]


def test_classify_message_includes_person_match_in_prompt():
    payload = {
        "message_type": "human", "importance": "high", "action_required": False,
        "keep_in_inbox": True, "digest_worthy": False, "person_org_signal": None,
        "confidence": 0.8, "reasoning": "known contact",
    }
    client = _fake_client_returning(payload)
    classify_message(client, "s", "sn", "b", {}, {"person_id": "p1", "person_name": "Blaine Rout"})
    prompt = client.models.generate_content.call_args.kwargs["contents"]
    assert "Blaine Rout" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_classifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classifier'`

- [ ] **Step 3: Write minimal implementation**

Create `classifier.py`:

```python
import json

from google import genai

_MODEL = "gemini-2.5-flash-lite"

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "message_type": {"type": "string", "enum": [
            "human", "newsletter", "marketing", "receipt", "notification",
            "account_service", "government_community", "school",
            "political_advocacy", "automated_other", "uncertain",
        ]},
        "importance": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
        "action_required": {"type": "boolean"},
        "keep_in_inbox": {"type": "boolean"},
        "digest_worthy": {"type": "boolean"},
        "person_org_signal": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": [
        "message_type", "importance", "action_required", "keep_in_inbox",
        "digest_worthy", "person_org_signal", "confidence", "reasoning",
    ],
}

_SAFE_DEFAULT = {
    "message_type": "uncertain",
    "importance": "medium",
    "action_required": False,
    "keep_in_inbox": True,
    "digest_worthy": False,
    "person_org_signal": None,
    "confidence": 0.0,
}


def make_client(api_key: str):
    return genai.Client(api_key=api_key)


def _build_prompt(subject: str, snippet: str, body: str, signals: dict, person_match: dict | None) -> str:
    person_line = "unknown sender, not in your contacts"
    if person_match:
        person_line = f"known contact: {person_match['person_name']}"
    return (
        "Classify this email for a personal inbox triage system. "
        "Be conservative: if uncertain, prefer keep_in_inbox=true.\n\n"
        f"Subject: {subject}\n"
        f"Snippet: {snippet}\n"
        f"Body excerpt: {body[:2000]}\n"
        f"Signals: {json.dumps(signals)}\n"
        f"Sender: {person_line}\n"
    )


def classify_message(client, subject: str, snippet: str, body: str, signals: dict, person_match: dict | None) -> dict:
    try:
        prompt = _build_prompt(subject, snippet, body, signals, person_match)
        response = client.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config={"response_mime_type": "application/json", "response_schema": _RESPONSE_SCHEMA},
        )
        return json.loads(response.text)
    except Exception as error:
        result = dict(_SAFE_DEFAULT)
        result["reasoning"] = f"Classification failed, defaulting to safe values: {error}"
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_classifier.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add classifier.py tests/test_classifier.py
git commit -m "Add Gemini structured classification with safe-default fallback"
```

- [ ] **Step 6: Manual verification against real Gemini**

```bash
python -c "
from config import load_config
from classifier import make_client, classify_message
cfg = load_config()
client = make_client(cfg.gemini_api_key)
result = classify_message(client, 'This Week in Greencastle', 'newsletter preview text',
                           'Unsubscribe at the bottom of this email.', {'has_list_unsubscribe': True}, None)
print(result)
"
```

Expected: a real JSON dict with all 8 fields, `message_type` likely `newsletter`, `keep_in_inbox: true`.

---

### Task 8: Gmail OAuth setup and client

**Files:**
- Create: `gmail_auth_setup.py`
- Create: `gmail_client.py`
- Test: `tests/test_gmail_client.py`

**Interfaces:**
- Consumes: `Config` (Task 1).
- Produces: `gmail_client.build_service(config) -> googleapiclient.discovery.Resource`; `gmail_client.fetch_new_messages(service, last_history_id: str | None) -> tuple[list[dict], str]` returning `(messages, new_history_id)` where each message dict is `{"gmail_message_id": str, "thread_id": str, "sender_email": str, "sender_name": str, "subject": str, "received_at": str, "snippet": str, "body": str, "headers": dict}`.

- [ ] **Step 1: Write the failing tests (mocked Gmail API)**

Create `tests/test_gmail_client.py`:

```python
import base64
from unittest.mock import MagicMock

from gmail_client import fetch_new_messages


def _make_message_payload(gmail_id, subject, sender):
    body_text = "Hello, this is the body."
    encoded_body = base64.urlsafe_b64encode(body_text.encode()).decode()
    return {
        "id": gmail_id,
        "threadId": f"thread-{gmail_id}",
        "snippet": "Hello, this is the...",
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "Date", "value": "Sat, 15 Aug 2026 07:00:00 -0400"},
            ],
            "mimeType": "text/plain",
            "body": {"data": encoded_body},
        },
    }


def test_fetch_new_messages_scopes_query_to_inbox():
    service = MagicMock()
    service.users().history().list().execute.return_value = {"history": [], "historyId": "999"}
    fetch_new_messages(service, last_history_id="100")
    call_kwargs = service.users().history().list.call_args.kwargs
    assert call_kwargs["labelId"] == "INBOX"
    assert call_kwargs["startHistoryId"] == "100"


def test_fetch_new_messages_parses_message_fields():
    service = MagicMock()
    service.users().history().list().execute.return_value = {
        "history": [{"messagesAdded": [{"message": {"id": "msg-1"}}]}],
        "historyId": "1001",
    }
    service.users().messages().get().execute.return_value = _make_message_payload(
        "msg-1", "Hello there", "Jane Somebody <jane@example.com>"
    )
    messages, new_history_id = fetch_new_messages(service, last_history_id="1000")
    assert new_history_id == "1001"
    assert len(messages) == 1
    assert messages[0]["gmail_message_id"] == "msg-1"
    assert messages[0]["subject"] == "Hello there"
    assert messages[0]["sender_email"] == "jane@example.com"
    assert messages[0]["sender_name"] == "Jane Somebody"
    assert "Hello, this is the body." in messages[0]["body"]


def test_fetch_new_messages_no_history_id_does_full_inbox_scan():
    service = MagicMock()
    service.users().messages().list().execute.return_value = {"messages": [{"id": "msg-1"}]}
    service.users().messages().get().execute.return_value = _make_message_payload(
        "msg-1", "First run", "Someone <someone@example.com>"
    )
    service.users().history().list().execute.return_value = {"historyId": "500"}
    messages, new_history_id = fetch_new_messages(service, last_history_id=None)
    assert len(messages) == 1
    assert new_history_id == "500"
    list_call_kwargs = service.users().messages().list.call_args.kwargs
    assert list_call_kwargs["q"] == "in:inbox"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gmail_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gmail_client'`

- [ ] **Step 3: Write minimal implementation**

Create `gmail_client.py`:

```python
import base64
import email.utils

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def build_service(config):
    credentials = Credentials(
        token=None,
        refresh_token=config.google_refresh_token,
        client_id=config.google_client_id,
        client_secret=config.google_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=_SCOPES,
    )
    return build("gmail", "v1", credentials=credentials)


def _decode_body(payload: dict) -> str:
    body_data = payload.get("body", {}).get("data")
    if body_data:
        return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        if part.get("mimeType") == "text/plain":
            return _decode_body(part)
    return ""


def _parse_message(raw: dict) -> dict:
    headers = {h["name"]: h["value"] for h in raw["payload"]["headers"]}
    sender_name, sender_email = email.utils.parseaddr(headers.get("From", ""))
    return {
        "gmail_message_id": raw["id"],
        "thread_id": raw["threadId"],
        "sender_email": sender_email,
        "sender_name": sender_name or sender_email,
        "subject": headers.get("Subject", ""),
        "received_at": headers.get("Date", ""),
        "snippet": raw.get("snippet", ""),
        "body": _decode_body(raw["payload"]),
        "headers": headers,
    }


def fetch_new_messages(service, last_history_id: str | None) -> tuple[list[dict], str]:
    message_ids: list[str] = []

    if last_history_id:
        history_response = service.users().history().list(
            userId="me", startHistoryId=last_history_id, labelId="INBOX"
        ).execute()
        for record in history_response.get("history", []):
            for added in record.get("messagesAdded", []):
                message_ids.append(added["message"]["id"])
        new_history_id = history_response["historyId"]
    else:
        list_response = service.users().messages().list(userId="me", q="in:inbox").execute()
        message_ids = [m["id"] for m in list_response.get("messages", [])]
        new_history_id = service.users().history().list(userId="me", startHistoryId="1").execute()["historyId"]

    messages = []
    for message_id in message_ids:
        raw = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        messages.append(_parse_message(raw))

    return messages, new_history_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gmail_client.py -v`
Expected: 3 passed

- [ ] **Step 5: Create the one-time OAuth consent script**

Create `gmail_auth_setup.py`:

```python
"""
Run this once to mint a refresh token: `python gmail_auth_setup.py`
Opens a browser for you to consent, then prints the refresh token to paste
into .env as GOOGLE_REFRESH_TOKEN.

Before running: in Google Cloud Console, register a Desktop app OAuth
client, add yourself as a test user, and note the client ID/secret in .env.
After running: go to the OAuth consent screen and click "Publish App"
(Testing -> In production, skip verification) to avoid the 7-day refresh
token expiry that applies while the app stays in Testing status.
"""
import os

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main():
    client_config = {
        "installed": {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, _SCOPES)
    credentials = flow.run_local_server(port=0)
    print("\nSuccess. Paste this into .env as GOOGLE_REFRESH_TOKEN:\n")
    print(credentials.refresh_token)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Manual verification — mint a real refresh token and fetch real inbox mail**

```bash
python gmail_auth_setup.py
```

Expected: a browser window opens, you approve access to your own Gmail (you'll see the "unverified app" warning — click "Advanced" -> "Go to [app name]" since it's your own app), and a refresh token prints to the terminal. Paste it into `.env` as `GOOGLE_REFRESH_TOKEN`. Then go to the Google Cloud Console OAuth consent screen and click **Publish App**.

Then confirm real ingestion works:

```bash
python -c "
from config import load_config
from gmail_client import build_service, fetch_new_messages
cfg = load_config()
service = build_service(cfg)
messages, history_id = fetch_new_messages(service, last_history_id=None)
print(f'Fetched {len(messages)} inbox messages, history_id={history_id}')
if messages:
    print(messages[0]['subject'], messages[0]['sender_email'])
"
```

Expected: prints a real count of your current inbox messages and the first one's real subject/sender.

- [ ] **Step 7: Commit**

```bash
git add gmail_client.py gmail_auth_setup.py tests/test_gmail_client.py
git commit -m "Add Gmail OAuth setup script and read-only inbox client"
```

---

### Task 9: Notepad log and Notion "Latest Run" page

**Files:**
- Create: `agent_log.py`
- Test: `tests/test_agent_log.py`

**Interfaces:**
- Consumes: `notion_client.NotionClient` (Task 4), `store` (Task 2).
- Produces: `agent_log.append_run_summary(log_path: str, run_at: str, results: list[dict], unmatched: list[dict], errors: list[str]) -> str` (returns the markdown section written, for reuse in the Notion update); `agent_log.update_latest_run_page(client, config, conn, markdown: str) -> str` (returns the page id, creating it on first call and reusing it thereafter via a row in a new tiny `notion_pages` table — see Step 3).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_log.py`:

```python
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
    client.create_standalone_page.return_value = {"id": "page-1"}
    conn = store.init_db(":memory:")
    config = MagicMock()

    page_id_1 = update_latest_run_page(client, config, conn, "## Run 1\nsummary")
    assert page_id_1 == "page-1"
    client.create_standalone_page.assert_called_once()

    page_id_2 = update_latest_run_page(client, config, conn, "## Run 2\nsummary")
    assert page_id_2 == "page-1"
    client.create_standalone_page.assert_called_once()  # still only called once
    client.update_page.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_log.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_log'`

- [ ] **Step 3: Write minimal implementation**

Create `agent_log.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_log.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add agent_log.py tests/test_agent_log.py
git commit -m "Add notepad log and Notion Latest Run page with page-id caching"
```

- [ ] **Step 6: Manual verification against real Notion**

```bash
python -c "
from config import load_config
from notion_client import NotionClient
from agent_log import update_latest_run_page
import store
cfg = load_config()
conn = store.init_db(cfg.db_path)
client = NotionClient(cfg.notion_token)
page_id = update_latest_run_page(client, cfg, conn, '## Test run\nHello from Phase 1 setup.')
print(page_id)
"
```

Expected: a real Notion page titled "Email Agent — Latest Run" appears in your workspace with that content. Run the command twice — confirm the second run updates the same page rather than creating a new one.

---

### Task 10: Ingestion entrypoint (`main.py`)

**Files:**
- Create: `main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: everything from Tasks 1–9.
- Produces: `main.run(dry_run: bool = False) -> dict` returning `{"status": str, "messages_processed": int}`. This is what a future scheduler (Phase 1b) calls; `if __name__ == "__main__"` parses `--dry-run` and calls it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_main.py`:

```python
from unittest.mock import MagicMock, patch

import store


@patch("main.build_service")
@patch("main.fetch_new_messages")
@patch("main.make_client")
@patch("main.classify_message")
@patch("main.NotionClient")
@patch("main.PeopleCache")
@patch("main.reconcile_sender")
@patch("main.update_latest_run_page")
def test_run_processes_messages_and_updates_checkpoint(
    mock_update_page, mock_reconcile, mock_cache_cls, mock_notion_cls,
    mock_classify, mock_gemini_client, mock_fetch, mock_gmail_service, tmp_path, monkeypatch
):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "x")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "x")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("NOTION_TOKEN", "x")
    monkeypatch.setenv("NOTION_PEOPLE_DATA_SOURCE_ID", "x")
    monkeypatch.setenv("NOTION_ORGANIZATIONS_DATA_SOURCE_ID", "x")
    monkeypatch.setenv("NOTION_AFFILIATIONS_DATA_SOURCE_ID", "x")
    monkeypatch.setenv("NOTION_EMAIL_ADDRESSES_DATA_SOURCE_ID", "x")
    monkeypatch.setenv("NOTION_EMAIL_DIGESTS_DATA_SOURCE_ID", "x")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("LOG_PATH", str(tmp_path / "log.md"))

    mock_fetch.return_value = ([{
        "gmail_message_id": "msg-1", "thread_id": "t1", "sender_email": "a@x.com",
        "sender_name": "A Sender", "subject": "Hi", "received_at": "2026-08-15T07:00:00Z",
        "snippet": "hi", "body": "hi there", "headers": {},
    }], "history-2")

    mock_classify.return_value = {
        "message_type": "human", "importance": "high", "action_required": True,
        "keep_in_inbox": True, "digest_worthy": False, "person_org_signal": None,
        "confidence": 0.9, "reasoning": "looks real",
    }
    mock_cache_cls.load.return_value = MagicMock(match_by_email=lambda e: None)
    mock_reconcile.return_value = {"action": "no_action"}

    import main
    result = main.run(dry_run=False)

    assert result["status"] == "ok"
    assert result["messages_processed"] == 1

    conn = store.init_db(str(tmp_path / "test.db"))
    rows = conn.execute("SELECT gmail_message_id FROM messages").fetchall()
    assert [r[0] for r in rows] == ["msg-1"]
    sync_state = conn.execute("SELECT last_history_id FROM sync_state").fetchone()
    assert sync_state[0] == "history-2"


@patch("main.build_service")
@patch("main.fetch_new_messages")
@patch("main.make_client")
@patch("main.classify_message")
@patch("main.NotionClient")
@patch("main.PeopleCache")
@patch("main.reconcile_sender")
@patch("main.update_latest_run_page")
def test_run_classifier_failure_keeps_message_in_inbox(
    mock_update_page, mock_reconcile, mock_cache_cls, mock_notion_cls,
    mock_classify, mock_gemini_client, mock_fetch, mock_gmail_service, tmp_path, monkeypatch
):
    for name, value in {
        "GOOGLE_CLIENT_ID": "x", "GOOGLE_CLIENT_SECRET": "x", "GOOGLE_REFRESH_TOKEN": "x",
        "GEMINI_API_KEY": "x", "NOTION_TOKEN": "x", "NOTION_PEOPLE_DATA_SOURCE_ID": "x",
        "NOTION_ORGANIZATIONS_DATA_SOURCE_ID": "x", "NOTION_AFFILIATIONS_DATA_SOURCE_ID": "x",
        "NOTION_EMAIL_ADDRESSES_DATA_SOURCE_ID": "x", "NOTION_EMAIL_DIGESTS_DATA_SOURCE_ID": "x",
        "DB_PATH": str(tmp_path / "test.db"), "LOG_PATH": str(tmp_path / "log.md"),
    }.items():
        monkeypatch.setenv(name, value)

    mock_fetch.return_value = ([{
        "gmail_message_id": "msg-1", "thread_id": "t1", "sender_email": "a@x.com",
        "sender_name": "A Sender", "subject": "Hi", "received_at": "2026-08-15T07:00:00Z",
        "snippet": "hi", "body": "hi there", "headers": {},
    }], "history-2")
    mock_classify.return_value = {
        "message_type": "uncertain", "importance": "medium", "action_required": False,
        "keep_in_inbox": True, "digest_worthy": False, "person_org_signal": None,
        "confidence": 0.0, "reasoning": "Classification failed, defaulting to safe values: boom",
    }
    mock_cache_cls.load.return_value = MagicMock(match_by_email=lambda e: None)
    mock_reconcile.return_value = {"action": "no_action"}

    import main
    result = main.run(dry_run=False)
    assert result["status"] == "ok"

    conn = store.init_db(str(tmp_path / "test.db"))
    row = conn.execute("SELECT keep_in_inbox FROM messages WHERE gmail_message_id = 'msg-1'").fetchone()
    assert row[0] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Write minimal implementation**

Create `main.py`:

```python
import argparse
import datetime

from classifier import classify_message, make_client
from config import load_config
from gmail_client import build_service, fetch_new_messages
from notion_client import NotionClient
from people_lookup import PeopleCache
from reconciliation import reconcile_sender
from agent_log import append_run_summary, update_latest_run_page
from signals import extract_signals
import store


def run(dry_run: bool = False) -> dict:
    config = load_config()
    conn = store.init_db(config.db_path)
    run_at = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")

    try:
        gmail_service = build_service(config)
        sync_state = store.get_sync_state(conn)
        last_history_id = sync_state["last_history_id"] if sync_state else None
        messages, new_history_id = fetch_new_messages(gmail_service, last_history_id)
    except Exception as error:
        store.insert_run_log(conn, run_at, 0, "auth_error", str(error))
        return {"status": "auth_error", "messages_processed": 0}

    notion_client = NotionClient(config.notion_token)
    people_cache = PeopleCache.load(notion_client, config)
    gemini_client = make_client(config.gemini_api_key)

    results, unmatched, errors = [], [], []

    for message in messages:
        sig = extract_signals(message["headers"], message["sender_email"])
        person_match = people_cache.match_by_email(message["sender_email"])
        classification = classify_message(
            gemini_client, message["subject"], message["snippet"], message["body"], sig, person_match
        )

        is_human = classification["message_type"] == "human"
        reconciliation_result = reconcile_sender(
            notion_client, config, people_cache, message["sender_email"],
            message["sender_name"], is_human, dry_run,
        )
        if reconciliation_result["action"] in ("created_person",) and not person_match:
            unmatched.append({
                "sender_email": message["sender_email"],
                "sender_name": message["sender_name"],
                "subject": message["subject"],
            })

        row = {
            "gmail_message_id": message["gmail_message_id"],
            "thread_id": message["thread_id"],
            "sender_email": message["sender_email"],
            "sender_name": message["sender_name"],
            "subject": message["subject"],
            "received_at": message["received_at"],
            "snippet": message["snippet"],
            "message_type": classification["message_type"],
            "importance": classification["importance"],
            "action_required": int(classification["action_required"]),
            "keep_in_inbox": int(classification["keep_in_inbox"]),
            "digest_worthy": int(classification["digest_worthy"]),
            "confidence": classification["confidence"],
            "reasoning": classification["reasoning"],
            "person_org_signal": classification["person_org_signal"],
            "matched_person_id": person_match["person_id"] if person_match else None,
            "matched_org_ids": None,
            "processed_at": datetime.datetime.utcnow().isoformat(),
        }
        if not dry_run:
            store.upsert_message(conn, row)
        results.append({**row, "action_required": bool(row["action_required"]), "keep_in_inbox": bool(row["keep_in_inbox"])})

    markdown = append_run_summary(config.log_path, run_at, results, unmatched, errors)
    if not dry_run:
        update_latest_run_page(notion_client, config, conn, markdown)
        store.set_sync_state(conn, new_history_id, run_at)
        store.insert_run_log(conn, run_at, len(messages), "ok", None)

    return {"status": "ok", "messages_processed": len(messages)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    outcome = run(dry_run=args.dry_run)
    print(outcome)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "Add main.py ingestion entrypoint with --dry-run support"
```

- [ ] **Step 6: Manual verification — full pipeline against real data**

```bash
python main.py --dry-run
```

Expected: prints `{'status': 'ok', 'messages_processed': N}` for real; check `logs/agent_log.md` for a real run summary. Review it carefully — this is the first end-to-end look at real classifications.

If it looks right:

```bash
python main.py
```

Expected: same, but this time real Notion writes happen for any reconciliation actions, and the local SQLite `messages` table gets real rows. Check the Notion "Email Agent — Latest Run" page updated with this run's summary.

---

### Task 11: Daily/weekly digest generator

**Files:**
- Create: `digest.py`
- Test: `tests/test_digest.py`

**Interfaces:**
- Consumes: `store` (Task 2), `notion_client.NotionClient` (Task 4), Gemini client from `classifier.make_client` (Task 7).
- Produces: `digest.group_routine_messages(messages: list[dict]) -> dict` (pure, deterministic — `{"newsletter": {"count": int, "senders": list[str]}, ...}`); `digest.phrase_digest(gemini_client, groups: dict) -> str`; `digest.build_attention_recap(messages: list[dict]) -> list[str]`; `digest.generate_digest(config, conn, notion_client, gemini_client, period: str) -> str` (returns the Notion page id created).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_digest.py`:

```python
import json
from unittest.mock import MagicMock

from digest import group_routine_messages, phrase_digest, build_attention_recap


def test_group_routine_messages_counts_and_groups_by_type_and_sender():
    messages = [
        {"message_type": "newsletter", "sender_name": "X Weekly", "digest_worthy": 1},
        {"message_type": "newsletter", "sender_name": "Y News", "digest_worthy": 1},
        {"message_type": "notification", "sender_name": "Library", "digest_worthy": 1},
    ]
    groups = group_routine_messages(messages)
    assert groups["newsletter"]["count"] == 2
    assert set(groups["newsletter"]["senders"]) == {"X Weekly", "Y News"}
    assert groups["notification"]["count"] == 1


def test_group_routine_messages_ignores_non_digest_worthy():
    messages = [{"message_type": "human", "sender_name": "Blaine Rout", "digest_worthy": 0}]
    groups = group_routine_messages(messages)
    assert groups == {}


def test_build_attention_recap_includes_high_importance_and_action_required():
    messages = [
        {"importance": "high", "action_required": 1, "sender_name": "Blaine Rout", "subject": "Draft", "reasoning": "needs feedback"},
        {"importance": "low", "action_required": 0, "sender_name": "X Weekly", "subject": "Newsletter", "reasoning": "routine"},
    ]
    recap = build_attention_recap(messages)
    assert len(recap) == 1
    assert "Blaine Rout" in recap[0]


def test_phrase_digest_passes_exact_groups_to_gemini():
    client = MagicMock()
    response = MagicMock()
    response.text = "You received 2 newsletters from X Weekly and Y News."
    client.models.generate_content.return_value = response

    groups = {"newsletter": {"count": 2, "senders": ["X Weekly", "Y News"]}}
    text = phrase_digest(client, groups)

    assert text == "You received 2 newsletters from X Weekly and Y News."
    prompt = client.models.generate_content.call_args.kwargs["contents"]
    assert json.dumps(groups) in prompt or "X Weekly" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_digest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'digest'`

- [ ] **Step 3: Write minimal implementation**

Create `digest.py`:

```python
import argparse
import datetime
import json

from classifier import make_client
from config import load_config
from notion_client import NotionClient
import store

_DIGEST_MODEL = "gemini-2.5-flash-lite"


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
    now = datetime.datetime.utcnow()
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_digest.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add digest.py tests/test_digest.py
git commit -m "Add daily/weekly digest generator with deterministic grouping"
```

- [ ] **Step 6: Manual verification against real data**

Once Task 10's manual run has stored some real messages:

```bash
python digest.py --period daily
```

Expected: prints `Digest created: <page-id>`, and a real page appears in the Email Digests Notion database with a "Needs your attention" section and a natural-language routine-mail summary matching the actual counts in your local SQLite (`sqlite3 data/email_agent.db "SELECT message_type, count(*) FROM messages WHERE digest_worthy=1 GROUP BY message_type"` to cross-check).

---

### Task 12: Feedback capture CLI

**Files:**
- Create: `feedback.py`
- Test: `tests/test_feedback.py`

**Interfaces:**
- Consumes: `store` (Task 2).
- Produces: `feedback.list_recent(conn, limit: int = 10) -> list[dict]`; `feedback.record_correction(conn, gmail_message_id: str, original: dict, corrected_fields: dict, note: str) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_feedback.py`:

```python
import json

import store
from feedback import list_recent, record_correction


def test_list_recent_returns_messages():
    conn = store.init_db(":memory:")
    store.upsert_message(conn, {
        "gmail_message_id": "msg-1", "thread_id": "t", "sender_email": "a@x.com",
        "sender_name": "A", "subject": "Test subject", "received_at": "2026-08-15T07:00:00Z",
        "snippet": "", "message_type": "newsletter", "importance": "low", "action_required": 0,
        "keep_in_inbox": 1, "digest_worthy": 1, "confidence": 0.9, "reasoning": "r",
        "person_org_signal": None, "matched_person_id": None, "matched_org_ids": None,
        "processed_at": "2026-08-15T07:00:01Z",
    })
    recent = list_recent(conn, limit=5)
    assert len(recent) == 1
    assert recent[0]["subject"] == "Test subject"


def test_record_correction_stores_snapshot_and_correction():
    conn = store.init_db(":memory:")
    store.upsert_message(conn, {
        "gmail_message_id": "msg-1", "thread_id": "t", "sender_email": "a@x.com",
        "sender_name": "A", "subject": "Test subject", "received_at": "2026-08-15T07:00:00Z",
        "snippet": "", "message_type": "newsletter", "importance": "low", "action_required": 0,
        "keep_in_inbox": 1, "digest_worthy": 1, "confidence": 0.9, "reasoning": "r",
        "person_org_signal": None, "matched_person_id": None, "matched_org_ids": None,
        "processed_at": "2026-08-15T07:00:01Z",
    })
    record_correction(
        conn, "msg-1",
        original={"importance": "low"},
        corrected_fields={"importance": "high"},
        note="this was actually urgent",
    )
    rows = conn.execute("SELECT gmail_message_id, original_classification, corrected_fields, note FROM feedback").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "msg-1"
    assert json.loads(rows[0][1]) == {"importance": "low"}
    assert json.loads(rows[0][2]) == {"importance": "high"}
    assert rows[0][3] == "this was actually urgent"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_feedback.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'feedback'`

- [ ] **Step 3: Write minimal implementation**

Create `feedback.py`:

```python
import datetime
import json

from config import load_config
import store


def list_recent(conn, limit: int = 10) -> list[dict]:
    return store.get_recent_messages(conn, limit)


def record_correction(conn, gmail_message_id: str, original: dict, corrected_fields: dict, note: str) -> None:
    store.insert_feedback(
        conn,
        gmail_message_id=gmail_message_id,
        original_classification=json.dumps(original),
        corrected_fields=json.dumps(corrected_fields),
        note=note,
        corrected_at=datetime.datetime.utcnow().isoformat(),
    )


def _prompt_for_correction(message: dict) -> dict:
    print(f"\nSubject: {message['subject']}")
    print(f"From: {message['sender_name']} <{message['sender_email']}>")
    print(f"Current: type={message['message_type']}, importance={message['importance']}, "
          f"action_required={bool(message['action_required'])}, keep_in_inbox={bool(message['keep_in_inbox'])}")

    corrected = {}
    new_importance = input("Correct importance (critical/high/medium/low, blank to skip): ").strip()
    if new_importance:
        corrected["importance"] = new_importance
    new_type = input("Correct message_type (blank to skip): ").strip()
    if new_type:
        corrected["message_type"] = new_type
    note = input("Note (why was this wrong?): ").strip()
    return corrected, note


def main():
    config = load_config()
    conn = store.init_db(config.db_path)
    recent = list_recent(conn, limit=10)

    for i, message in enumerate(recent):
        print(f"{i}: [{message['message_type']}] {message['subject']} — {message['sender_name']}")

    choice = input("\nWhich message needs a correction (index, or blank to quit)? ").strip()
    if not choice:
        return
    message = recent[int(choice)]
    corrected_fields, note = _prompt_for_correction(message)
    original = {
        "message_type": message["message_type"],
        "importance": message["importance"],
        "action_required": bool(message["action_required"]),
        "keep_in_inbox": bool(message["keep_in_inbox"]),
    }
    record_correction(conn, message["gmail_message_id"], original, corrected_fields, note)
    print("Recorded.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_feedback.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add feedback.py tests/test_feedback.py
git commit -m "Add feedback-capture CLI for correcting stored classifications"
```

- [ ] **Step 6: Manual verification against real data**

```bash
python feedback.py
```

Expected: lists your real recently-processed messages, lets you pick one and correct it interactively; confirm the correction landed with `sqlite3 data/email_agent.db "SELECT * FROM feedback"`.

---

## Self-Review Notes

- **Spec coverage:** §1 goal (Task 10), §2 non-goals (respected throughout — no Gmail mutation code exists anywhere), §3 architecture (Tasks 1–12 match the diagram), §4 components (one task per component), §5 Gmail auth incl. Publish App (Task 8), §6 classification schema (Task 7), §6a notepad log (Task 9), §6b reconciliation incl. name-match threshold and dry-run (Tasks 5–6), §6c digest (Task 11), §6d feedback (Task 12), §7 data model (Task 2), §8 idempotency (Task 2's upsert + Task 10's checkpoint-after-success ordering), §9 error handling (Task 10's try/except around Gmail fetch vs. per-message classifier fallback from Task 7), §10 known limitations (reflected in Task 6's threshold and Task 8/11 notes), §11 secrets (Task 1), §12 testing strategy (mocked unit tests + manual real-data steps in every task), §13 future work (untouched, correctly out of scope).
- **Placeholder scan:** none found — every step has runnable code and literal expected output.
- **Type consistency:** `message` dict shape is identical across `store.py`, `gmail_client.py`, `main.py`, `digest.py`, and `feedback.py` (same key names throughout); `reconcile_sender`'s return shape is consistent between Task 6's implementation and Task 10's consumption of `action`.
