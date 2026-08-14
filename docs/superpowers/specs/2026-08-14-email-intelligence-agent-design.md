# Email Intelligence Agent — Phase 1 (Observe-Only)

Status: design in progress, pending implementation plan
Owner: Kevin Verhoff

**Deployment staging:** Phase 1 runs entirely locally (manual invocation,
local SQLite, local log file). GitHub Actions scheduling and Cloudflare D1
are deferred until the pipeline is proven locally — see §3 and §7.

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
  or filter changes. The daily/weekly digest (§6c) is written to Notion and
  the local log — it is never sent as an email; producing it is in scope,
  delivering it via Gmail is not.
- Monitoring any account other than personal Gmail.
- Signature/domain-based Organization and Affiliation auto-inference (moved
  to a v1.1 fast-follow — see §6b step 3 and §10). v1 auto-creates People and
  Email Addresses only, deliberately, to avoid testing the riskiest new logic
  in the same release as the unvalidated core classification loop.
- Silently merging two different People who happen to share a name, or
  overwriting a Person/Organization's already-`Confirmed` data without
  flagging it. (Note: this phase *does* auto-create/auto-update People,
  Email Addresses, Organizations, and Affiliations from discovered senders —
  see §6b — but every such write is marked `Needs Review` / `Inferred`, never
  silently treated as settled fact.)
- Cost/volume optimization (e.g. a rules-first funnel that skips the LLM for
  obvious bulk mail). Every message gets a full classification pass in this
  phase; optimization is deferred until real volume is observed.

## 3. Architecture

**Phase 1 (now): local.**

```
You, running `python main.py [--dry-run]` on your own machine
  └─ Python job (single entrypoint, run to completion each invocation)
       ├─ gmail_client: OAuth2 (gmail.readonly), fetch messages since last
       │    checkpoint, scoped to `in:inbox` only — mail your existing
       │    filters already routed elsewhere is not reprocessed here
       ├─ people_lookup: loads all People/Emails/Organizations into memory
       │    once per run (small dataset), matches each sender against that
       │    cache rather than querying Notion per message
       ├─ classifier: one structured Gemini call per message → 7-dimension
       │    judgment
       ├─ store: upsert results + checkpoint into a local SQLite file
       │    (schema-identical to the future D1 tables — see §7).
       │    `--dry-run` logs every Notion write §6b would make without
       │    making it
       └─ agent_log: append a human-readable run summary to a local
            "notepad" log file, and update the Notion "Email Agent —
            Latest Run" page

You, running `python digest.py --period daily|weekly` whenever you want it
  └─ reads stored messages for the window from SQLite, groups the routine
       ones, asks Gemini to phrase a summary (§6c), writes it to Notion +
       the notepad log

You, running `python feedback.py` to correct a stored classification (§6d)
```

All state lives in the local SQLite file (path from `DB_PATH` in `.env`).
Nothing is scheduled yet — you run it by hand while testing.

**Phase 1b (later, once this is proven): Cloudflare.** Swap the storage layer
to Cloudflare D1 (same schema, just a different `store.py` backend hitting
D1's HTTP API instead of local SQLite) and add a GitHub Actions workflow on
a cron schedule (4-6x/day) to replace manual invocation. No other component
changes — this is purely a deployment change, not a redesign.

## 4. Components

- `gmail_client.py` — loads OAuth2 credentials (client id/secret + stored
  refresh token), refreshes the access token, calls the Gmail API
  `users.history.list` (query scoped to `in:inbox`) to get message IDs
  changed since the last known `historyId`, then `users.messages.get` for
  each to pull headers, snippet, and body. Read-only scope only:
  `https://www.googleapis.com/auth/gmail.readonly`.
- `signals.py` — cheap, deterministic feature extraction from message
  headers: `List-Unsubscribe` presence, `Precedence`/bulk-mail headers,
  sender domain, whether the sender address matches a known automated
  pattern (e.g. `no-reply@`). These are passed to the classifier as context,
  never used to skip classification.
- `people_lookup.py` — at the start of each run, loads every People page (with
  linked Email Addresses and Organizations) into memory once, rather than
  querying Notion per message. Matching, in order: (1) exact match on any
  linked email address; (2) normalized display-name match (case/whitespace
  folded, common suffix/prefix like "Jr."/titles stripped) against an
  existing Person — only above a deliberately high similarity bar; anything
  weaker is logged as a possible match in the notepad log but **not** written
  to Notion at all, to keep spoofed/coincidental name matches from touching
  real records. Returns whatever is found (or nothing) for the classifier
  and for §6b to act on.
- `classifier.py` — builds a single Gemini prompt per message containing:
  subject/snippet/body excerpt, extracted signals, and any People/Org match
  context. Calls Gemini with a `response_schema` for guaranteed structured
  JSON (same pattern as `voice-notes/src/worker.js`). Returns the 7-dimension
  result (§6).
- `store.py` — SQLite client (Python's built-in `sqlite3`, no extra
  dependency) against the local `DB_PATH` file. Upserts one row per message
  (keyed by `gmail_message_id`, so re-processing the same message is
  harmless), updates `sync_state`, and appends to `run_log` and `feedback`
  (§6d). Written so the only thing that changes for the Phase 1b D1 swap is
  this file.
- `agent_log.py` — the "notepad" log: appends a timestamped, human-readable
  section to `LOG_PATH` (plain Markdown) every run — see §6a for format.
  Also updates the single Notion "Email Agent — Latest Run" page with the
  same summary, so it's checkable from your phone too. Shared by `main.py`
  and `digest.py`.
- `digest.py` — the daily/weekly digest generator (§6c). Separate entrypoint,
  run whenever you want one — nothing about it is scheduled in Phase 1.
- `feedback.py` — the correction-capture CLI (§6d). Separate entrypoint.
- `main.py` — orchestrates the ingestion components above in order. Accepts
  `--dry-run`, which runs the full pipeline but logs every People/Email
  Addresses/Organizations/Affiliations write §6b would make instead of
  actually making it — for testing the reconciliation logic without
  polluting the real Notion database. In Phase 1 you run this directly
  (`python main.py`); Phase 1b adds a GitHub Actions workflow that calls the
  same entrypoint on a cron schedule instead of you doing it by hand.

## 5. Gmail authentication

- OAuth2 **installed-app / desktop flow**, user-consent based (not a service
  account — this is a personal Gmail account, not a Workspace domain we
  administer).
- Scope: `gmail.readonly` only. No broader scope is requested in this phase.
- One-time setup: register a **Desktop app** OAuth client in Google Cloud
  Console (personal project), add yourself as a test user, run the consent
  flow once locally to obtain a refresh token. **Then click "Publish App"**
  on the OAuth consent screen (Testing → In production) **without**
  submitting for verification. This matters: `gmail.readonly` is a
  *restricted* scope, and Google expires refresh tokens after 7 days for any
  app still in Testing status, regardless of use — verified via Google's own
  docs. Publishing (unverified) removes that 7-day limit for a solo
  developer authorizing only their own account; Google explicitly exempts
  this case from needing a full verification review. The only visible cost
  is a one-time "unverified app" click-through on the consent screen, which
  only you will ever see. Store `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
  and `GOOGLE_REFRESH_TOKEN` in `.env` (Phase 1) / GitHub Actions secrets
  (Phase 1b). The job never re-runs the interactive consent flow — it only
  refreshes the access token using the stored refresh token.
- If the refresh token is ever revoked or expires (unused 6+ months, password
  change, or manual revocation — not expected in normal use once published),
  the job fails loudly (logs to `run_log` with status=`auth_error`) rather
  than silently skipping runs.

## 6. Classification schema (per message, via Gemini structured output)

Seven independent fields, never collapsed into one score:

1. `message_type` — enum: `human`, `newsletter`, `marketing`, `receipt`,
   `notification`, `account_service`, `government_community`, `school`,
   `political_advocacy`, `automated_other`, `uncertain`.
2. `importance` — enum: `critical`, `high`, `medium`, `low`.
3. `action_required` — boolean.
4. `keep_in_inbox` — boolean. **Defaults to `true` on any low-confidence or
   failed classification.**
5. `digest_worthy` — boolean. True for routine automated mail that doesn't
   need individual attention but should still be summarized in aggregate
   (`message_type` in `{newsletter, marketing, receipt, notification,
   account_service, automated_other}` and `action_required = false`). This
   is what `digest.py` (§6c) groups; it's computed once, here, at
   classification time — not recomputed by the digest step.
6. `person_org_signal` — optional structured note: does this message suggest
   a new affiliation, role change, or new-person detection worth a human's
   review? (Never auto-applied to Notion — just surfaced.)
7. `confidence` — float 0–1.

Plus a required `reasoning` string (free text) explaining the judgment, so
every decision is auditable.

## 6a. The notepad log

Every run appends one section to `LOG_PATH` (default `./logs/agent_log.md`),
never overwritten — a scrollable history you can open in any editor:

```markdown
## Run 2026-08-15 07:03

Processed 14 messages (12 matched to People, 2 unmatched senders).

- [human / high / action_required] "Re: Comprehensive Plan draft" — Blaine
  Rout (brout@cityofgreencastle.com) — Plan Commission is asking for your
  feedback by Friday. keep_in_inbox=true, confidence=0.91
- [newsletter / low] "This Week in Greencastle" — noreply@... —
  List-Unsubscribe present, no action needed. keep_in_inbox=true (not yet
  archived — Phase 1 never touches Gmail), confidence=0.97
- ...

**Unmatched senders (real person, not in People DB):**
- jane.somebody@example.com — "Jane Somebody" — re: "Volunteer schedule"

No errors this run.
```

Every message gets a line; nothing is summarized away. This is the primary
way you sanity-check the classifier while testing locally — the Notion page
mirrors the same summary for when you're away from your machine.

## 6b. Sender → Person reconciliation

People can now have multiple email addresses (Notion schema change: a new
**Email Addresses** database — Person relation, Email, Label, `Confidence`
— replaces the old single Email field on People, which supported only one
address per person). This removes the need for duplicate-candidate handling
in the common case: attaching an additional real address to someone already
known is never a conflict.

For each message's sender, in order:

1. **Exact match** against any of a Person's linked Email Addresses → known,
   nothing to do.
2. **No email match, but the sender's display name closely matches an
   existing Person** → attach the discovered address as a new Email
   Addresses row on that Person, `Confidence = Inferred - needs review`.
   True whether that Person already has zero or several addresses on file —
   this is exactly the "map real correspondence back onto the people we
   already know" case, and multi-email support means it's always just an
   addition, never a merge decision.
3. **No match at all, and the classifier judges this is a real human (not
   automated)** → auto-create a new Person (`Status = Needs Review`) and a
   new Email Addresses row (`Confidence = Inferred - needs review`) — name
   and email only, nothing else invented.
   **v1.1 fast-follow, not built now:** if the message body has a parseable
   signature block, extract any Title/Organization mentioned there and
   create/match that Organization plus an Affiliation row (`Confidence =
   Inferred - needs review`), same pattern as the WICAA/Plan Commission
   affiliations; also suggest an affiliation when the sender's email domain
   matches an existing Organization's Website domain even with no signature.
   Deferred deliberately — it's the least-tested, most heuristic part of this
   design, and shipping it alongside the unvalidated core classification
   loop would make debugging either one harder.

Every record this step writes is visibly marked as unconfirmed
(`Status`/`Confidence` = `Needs Review`/`Inferred`) — nothing the agent
writes is ever presented to Notion as settled fact. You review and flip
these at your own pace; the agent never re-flags something you've already
confirmed.

## 6c. Daily/weekly digest

Run manually with `python digest.py --period daily` or `--period weekly`.
Reads every stored message in the window from SQLite and splits it in two:

- **Needs your attention** — anything with `importance` in `{critical,
  high}` or `action_required = true`. Short bullet list, one line each:
  sender, subject, and the `reasoning` already stored for it. Nothing new is
  computed here — it's a recap of judgments already made per-message.
- **Routine mail** — every stored message with `digest_worthy = true` (§6).
  This is grouped and counted **deterministically in Python first** — by
  `message_type`, then by sender/sender-domain within each type — before any
  LLM involvement, so the actual counts can never be hallucinated. That structured grouping (e.g. `{"newsletter": {"count": 4,
  "senders": ["x", "y", "z", "a"]}, "notification": {"count": 1, "senders":
  ["library-noreply@..."], "note": "auto-renew, 4 books"}}`) is then handed
  to Gemini with an explicit instruction to phrase it as natural prose
  *using only the numbers and names given* — its job is wording, not
  counting. Example output:

  > You received 4 newsletters from X, Y, Z, and A, and an auto-renewal
  > notification from the library for 4 books. Nothing else needed your
  > attention today.

The digest (both sections) is written to Notion (a dated page, or appended
section — implementation detail for the plan) and to the notepad log. It is
**never sent as an email** — this is a read surface, not a Gmail action.

## 6d. Feedback capture

`python feedback.py` lists recent messages from SQLite with a short index,
lets you pick one, and records a correction: what you'd have classified it
as instead, plus an optional note. Corrections are stored in their own
`feedback` table (§7) — kept separate from `messages` because a correction
is retrospective judgment about a decision, not a new fact about the email
itself (matches the Memory/Knowledge/Feedback/Traces distinction from the
broader assistant plan). Nothing acts on feedback automatically in this
phase — it exists so that before ever building an approval-gated action
layer, we can look back and actually measure how often the classifier was
wrong, rather than deciding "it seems fine" from vibes.

## 7. Data model (local SQLite now, Cloudflare D1 later — identical schema)

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

CREATE TABLE feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  gmail_message_id TEXT,     -- references messages.gmail_message_id
  original_classification TEXT,  -- JSON snapshot of the 7 fields at the time
  corrected_fields TEXT,     -- JSON, only the fields you actually corrected
  note TEXT,
  corrected_at TEXT
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

- Sender-to-Person matching starts from a small base: 5 of the 32 people
  created from meeting history have a `Confirmed` work email on file (public
  officials, backfilled from official directories); the rest have none yet.
  §6b's reconciliation logic is exactly the mechanism that improves this over
  time — every real message from someone already in People gets their
  address attached automatically (flagged `Needs Review`, never silently
  trusted), so the database fills in the more this agent actually runs.
- Signature/domain-based Organization and Affiliation inference is explicitly
  deferred to v1.1 (§6b step 3), not built in this phase, specifically
  because it's the most heuristic and least-tested part of this design.
- Name-based matching (§6b step 2, §4 `people_lookup.py`) only ever writes to
  Notion above a deliberately high similarity bar; weaker matches are logged
  but not written, since display names are trivially spoofable and a wrong
  auto-attach pollutes a real Person record.
- This phase has no approve/reject action interface — "review" means reading
  the notepad log/Notion page and, for classification accuracy specifically,
  `feedback.py` (§6d). Acting on your own review (e.g. archiving) is a later
  phase.

## 11. Secrets / configuration

Phase 1: a local `.env` file (never committed; `env.example` in the repo
root documents every variable with no real values) — `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, `GEMINI_API_KEY`,
`NOTION_TOKEN`, `NOTION_PEOPLE_DATA_SOURCE_ID`,
`NOTION_ORGANIZATIONS_DATA_SOURCE_ID`, `NOTION_AFFILIATIONS_DATA_SOURCE_ID`,
`NOTION_EMAIL_ADDRESSES_DATA_SOURCE_ID`, `DB_PATH`, `LOG_PATH`.

Phase 1b adds `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_D1_DATABASE_ID`,
`CLOUDFLARE_API_TOKEN` as GitHub Actions encrypted secrets, at which point
the Google/Gemini/Notion values move there too.

## 12. Testing strategy

- Unit tests for `signals.py` (pure functions, easy to test) and the
  `store.py` upsert logic against a real local SQLite file (in-memory
  `sqlite3` for speed) — this doubles as the future D1 compatibility check,
  since D1's SQL dialect is SQLite.
- A `classifier.py` test using recorded fixture messages (a handful of real
  anonymized-shape examples per category) asserting the schema shape comes
  back correctly — not asserting exact classification content, since that's
  inherently probabilistic.
- A `digest.py` grouping-logic test with fixture message rows, asserting the
  deterministic counts/groupings are correct — the part that must never be
  wrong, since Gemini's phrasing pass is only as trustworthy as the numbers
  it's given.
- No automated tests hit live Gmail/Gemini/Notion; those are exercised by
  actually running `python main.py --dry-run` (safe against the real Notion
  database) and then without `--dry-run` against your real mailbox while
  developing — that's the whole point of testing locally first.

## 13. What comes after this phase

Not designed yet, intentionally: an approval-gated action layer (e.g.
archive-after-digest for newsletters, once `feedback.py` data shows the
classifier is trustworthy enough), the v1.1 signature/domain-based
Organization inference deferred from §6b, and expanding beyond personal
Gmail. Each is its own future design pass.
