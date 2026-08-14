# Email Intelligence Agent — Phase 1 (Observe-Only)

Status: approved design, pending implementation plan
Owner: Kevin Verhoff

## 1. Goal

Build the first phase of an Email Intelligence Agent for personal Gmail. This
phase is **strictly read-only**: it ingests messages, classifies them along
several independent dimensions, scores importance, looks up the sender
against the existing Notion People/Organizations knowledge layer, and stores
the results — but never archives, deletes, labels, moves, sends, or otherwise
mutates Gmail. The purpose is to build and validate the judgment layer before
any automation acts on it.

Guiding principle: **a false negative (archiving something important) is far
worse than a false positive (leaving a newsletter in the inbox).** Every
design choice below optimizes for recall over automation.

## 2. Non-goals (explicitly out of scope for this phase)

- Any Gmail mutation: archive, delete, label, move, mark read/unread, send,
  or filter changes.
- Generating and delivering an actual daily/weekly digest email or document.
  (This phase produces a lightweight per-run Notion summary for review, not
  a polished briefing product.)
- Monitoring any account other than personal Gmail.
- Automatically creating new People/Organizations records from discovered
  senders (mirrors the "don't invent" rule already applied to the
  People/Organizations database — new-person detection is surfaced for
  review, never auto-committed).
- Cost/volume optimization (e.g. a rules-first funnel that skips the LLM for
  obvious bulk mail). Every message gets a full classification pass in this
  phase; optimization is deferred until real volume is observed.

## 3. Architecture

```
GitHub Actions (cron, 4-6x/day)
  └─ Python job (single entrypoint, run to completion each invocation)
       ├─ gmail_client: OAuth2 (gmail.readonly), fetch messages since last
       │    checkpoint via Gmail history API
       ├─ people_lookup: match sender against Notion People/Organizations
       ├─ classifier: one structured Gemini call per message → 7-dimension
       │    judgment
       ├─ store: upsert results + checkpoint into Cloudflare D1 (via D1's
       │    REST API — plain HTTP, no Workers/bindings involved)
       └─ notion_digest: write/update a "Email Agent — Latest Run" Notion
            page summarizing the run
```

All state lives in Cloudflare D1. GitHub Actions runners are ephemeral, so
nothing is assumed to persist locally between runs — every run reads its
starting point from D1 and writes its ending point back before exiting.

## 4. Components

- `gmail_client.py` — loads OAuth2 credentials (client id/secret + stored
  refresh token), refreshes the access token, calls the Gmail API
  `users.history.list` to get message IDs changed since the last known
  `historyId`, then `users.messages.get` for each to pull headers, snippet,
  and body. Read-only scope only: `https://www.googleapis.com/auth/gmail.readonly`.
- `signals.py` — cheap, deterministic feature extraction from message
  headers: `List-Unsubscribe` presence, `Precedence`/bulk-mail headers,
  sender domain, whether the sender address matches a known automated
  pattern (e.g. `no-reply@`). These are passed to the classifier as context,
  never used to skip classification.
- `people_lookup.py` — queries the Notion People and Organizations data
  sources (reusing the existing MCP/REST patterns) to find a match for the
  sender's email or display name. Returns whatever is found: matched person
  page ID, VIP/importance flag, linked organizations/roles — or nothing.
- `classifier.py` — builds a single Gemini prompt per message containing:
  subject/snippet/body excerpt, extracted signals, and any People/Org match
  context. Calls Gemini with a `response_schema` for guaranteed structured
  JSON (same pattern as `voice-notes/src/worker.js`). Returns the 7-dimension
  result (§6).
- `store.py` — thin Cloudflare D1 REST client (`requests`-based). Upserts one
  row per message (keyed by `gmail_message_id`, so re-processing the same
  message is harmless), updates `sync_state`, and appends to `run_log`.
- `notion_digest.py` — after a run completes, writes a run summary to a
  single Notion page: counts by message type, anything flagged important or
  action-required with its reasoning, and any senders that read as a real
  person but didn't match anyone in People.
- `main.py` — orchestrates the above in order; this is the GitHub Actions
  entrypoint.
- `.github/workflows/ingest.yml` — cron schedule (4-6x/day, at off-minute
  times), sets up Python, installs dependencies, runs `main.py` with secrets
  injected as environment variables.

## 5. Gmail authentication

- OAuth2 **installed-app / desktop flow**, user-consent based (not a service
  account — this is a personal Gmail account, not a Workspace domain we
  administer).
- Scope: `gmail.readonly` only. No broader scope is requested in this phase.
- One-time setup: register an OAuth client in Google Cloud Console (personal
  project), run the consent flow once locally to obtain a refresh token,
  then store `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and
  `GOOGLE_REFRESH_TOKEN` as GitHub Actions encrypted secrets. The workflow
  never re-runs the interactive consent flow — it only refreshes the access
  token using the stored refresh token.
- If the refresh token is ever revoked or expires, the job fails loudly (logs
  to `run_log` with status=`auth_error`) rather than silently skipping runs.

## 6. Classification schema (per message, via Gemini structured output)

Seven independent fields, never collapsed into one score:

1. `message_type` — enum: `human`, `newsletter`, `marketing`, `receipt`,
   `notification`, `account_service`, `government_community`, `school`,
   `political_advocacy`, `automated_other`, `uncertain`.
2. `importance` — enum: `critical`, `high`, `medium`, `low`.
3. `action_required` — boolean.
4. `keep_in_inbox` — boolean. **Defaults to `true` on any low-confidence or
   failed classification.**
5. `digest_worthy` — boolean (relevant once a real digest is built later).
6. `person_org_signal` — optional structured note: does this message suggest
   a new affiliation, role change, or new-person detection worth a human's
   review? (Never auto-applied to Notion — just surfaced.)
7. `confidence` — float 0–1.

Plus a required `reasoning` string (free text) explaining the judgment, so
every decision is auditable.

## 7. Data model (Cloudflare D1)

```sql
CREATE TABLE messages (
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
  person_org_signal TEXT,       -- JSON, nullable
  matched_person_id TEXT,       -- nullable, Notion page ID
  matched_org_ids TEXT,         -- JSON array, nullable
  processed_at TEXT
);

CREATE TABLE sync_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),  -- single row
  last_history_id TEXT,
  last_run_at TEXT
);

CREATE TABLE run_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at TEXT,
  messages_processed INTEGER,
  status TEXT,        -- 'ok' | 'auth_error' | 'partial_error' | 'crashed'
  errors TEXT          -- JSON, nullable
);
```

## 8. Incremental sync & idempotency

- The Gmail `history.list` API gives changes since a `historyId` checkpoint,
  avoiding a full-mailbox re-scan every run.
- `messages` is keyed by `gmail_message_id` with an upsert (`INSERT ... ON
  CONFLICT DO UPDATE`), so reprocessing a message (e.g. after a crash before
  the checkpoint was saved) is harmless — same message, same result, no
  duplicate.
- The checkpoint (`sync_state.last_history_id`) is only updated **after**
  every message in the batch is successfully stored. If the run crashes
  partway through, the next run starts from the last known-good checkpoint
  and reprocesses the same batch — never skips messages on failure.

## 9. Error handling

- A single message's Gemini call failing does not fail the run — that
  message is stored with `keep_in_inbox = true`, `confidence = 0`,
  `message_type = 'uncertain'`, and `reasoning` set to the error, then
  processing continues to the next message.
- A Gmail API or D1 auth/connection failure fails the whole run: nothing is
  partially checkpointed, `run_log` gets a row with `status='auth_error'` or
  `'crashed'`, and the next scheduled run retries from the last good state.

## 10. Known limitations (stated upfront, not discovered later)

- Sender-to-Person matching depends on the People database having real email
  addresses recorded. Most of the 32 people created from meeting history
  don't have one yet (by design — we don't invent contact info). Matching
  will improve over time: (a) a small batch of public officials' published
  work emails is being backfilled now as a starting point, and (b) once this
  agent is live, real correspondent addresses seen in actual mail can be
  matched to People by name and backfilled with real confidence, rather than
  guessed.
- This phase has no user-facing action loop — "review" is a Notion page, not
  an approve/reject interface. That comes later once we're ready to move
  past observe-only.

## 11. Secrets / configuration (GitHub Actions encrypted secrets)

`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`,
`GEMINI_API_KEY`, `NOTION_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`,
`CLOUDFLARE_D1_DATABASE_ID`, `CLOUDFLARE_API_TOKEN`.

## 12. Testing strategy

- Unit tests for `signals.py` (pure functions, easy to test) and the D1
  upsert logic (against a local/in-memory SQLite standing in for D1's SQL
  dialect, which is SQLite-compatible).
- A `classifier.py` test using recorded fixture messages (a handful of real
  anonymized-shape examples per category) asserting the schema shape comes
  back correctly — not asserting exact classification content, since that's
  inherently probabilistic.
- No live Gmail/Gemini/D1 calls in CI; those are exercised manually against
  a real (test) mailbox before the first scheduled run goes live.

## 13. What comes after this phase

Not designed yet, intentionally: an approval-gated action layer (e.g.
archive-after-digest for newsletters), real daily/weekly briefing generation,
a feedback-capture mechanism to record corrections, and expanding beyond
personal Gmail. Each is its own future design pass.
