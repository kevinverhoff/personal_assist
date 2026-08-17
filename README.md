# personal_assist

Hi! I'm Kevin's personal assistant!

This repo is the first real piece of that: an **Email Intelligence Agent**
for personal Gmail. It reads your inbox, classifies each message along
several independent dimensions, cross-references the sender against a
Notion knowledge base of people/organizations you actually know, and
produces a human-readable summary and digest — all without ever touching
Gmail itself (no archive, delete, label, or send).

Full design rationale lives in
[`docs/superpowers/specs/2026-08-14-email-intelligence-agent-design.md`](docs/superpowers/specs/2026-08-14-email-intelligence-agent-design.md);
the task-by-task build record is in
[`docs/superpowers/plans/2026-08-14-email-intelligence-agent-phase1.md`](docs/superpowers/plans/2026-08-14-email-intelligence-agent-phase1.md).

## Where things stand

**Phase 1 (observe-only) is fully built and verified against real Gmail,
Gemini, and Notion data** — not just unit tests. 59 automated tests pass;
every external integration has also been run for real at least once.

What exists today:

- `gmail_client.py` / `gmail_auth_setup.py` — read-only Gmail ingestion
  (`gmail.readonly` scope only), scoped to `in:inbox`, incremental via
  Gmail's history API.
- `signals.py` — deterministic header signals (bulk mail, `no-reply@`, etc.)
  fed to the classifier as context.
- `classifier.py` — one Gemini call per message, returning 7 independent
  fields (type, importance, action-required, keep-in-inbox, digest-worthy,
  person/org signal, confidence) plus reasoning — never collapsed into a
  single score. Falls back to safe defaults (`keep_in_inbox=true`) on any
  failure.
- `people_lookup.py` / `reconciliation.py` — matches senders against the
  Notion People/Email Addresses databases, and auto-creates/attaches new
  People and Email Addresses for real senders not yet known — always
  marked `Needs Review` / `Inferred`, never presented as confirmed fact.
- `store.py` — local SQLite (schema designed to be a drop-in match for
  Cloudflare D1 later).
- `agent_log.py` — a local "notepad" log plus a single Notion "Latest Run"
  status page, updated in place each run.
- `digest.py` — `python digest.py --period daily|weekly` groups routine
  mail deterministically and has Gemini phrase (never count) a summary,
  written to a dedicated Notion "Email Digests" database.
- `feedback.py` — a CLI to correct a stored classification, so accuracy
  can eventually be measured rather than eyeballed.

Everything currently runs **locally, by hand** — no scheduling yet, no
Cloudflare. That's intentional (see Phase 1b below).

### In progress

A change to prioritize messages from people already in the Notion People
database first, then separately surface anything else that may need
attention — in the per-run summary, the Notion "Latest Run" page, and the
digest's attention recap. Design agreed; not yet implemented.

### Next steps

- **Known-people-first prioritization** (above) — implement, test, verify
  against real data.
- **Phase 1b**: move scheduling to GitHub Actions (cron, 4-6x/day) and
  storage to Cloudflare D1, once the local pipeline has run for a while
  and feels trustworthy. No other component changes expected — the store
  layer was written for exactly this swap.
- **v1.1**: signature/domain-based Organization and Affiliation inference
  for newly-discovered senders (deliberately deferred out of Phase 1 as
  the riskiest, least-tested piece of the design).
- Eventually, an approval-gated action layer (e.g. archive-after-digest
  for newsletters) — only once `feedback.py` data shows the classifier is
  actually trustworthy enough to act on.

## Running it locally

**Prerequisites:** Python 3.11+, a Google Cloud project, a Gemini API key,
and a Notion integration already shared with the People / Organizations /
Affiliations / Email Addresses / Email Digests databases and the "Email
Agent" parent page.

1. **Set up the environment:**

   ```bash
   python -m venv .venv
   source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on macOS/Linux
   pip install -r requirements.txt
   ```

2. **Configure secrets:** copy `env.example` to `.env` and fill in real
   values. See `env.example` for exactly which keys are needed and where
   each one comes from (Google Cloud Console for the OAuth client, Google
   AI Studio for the Gemini key, notion.so/my-integrations for the Notion
   token). `GOOGLE_REFRESH_TOKEN` is the one exception — you can't just
   "go get" it, see the next step.

3. **One-time Gmail OAuth consent:**

   ```bash
   python gmail_auth_setup.py
   ```

   This opens a browser for you to log in and consent (you'll see an
   "unverified app" warning since this is your own personal OAuth client —
   click through it), then prints a refresh token to paste into `.env`.
   Afterwards, go to the OAuth consent screen in Google Cloud Console and
   click **Publish App** (Testing → In production, skip verification) —
   otherwise the refresh token expires after 7 days.

4. **Run the tests:**

   ```bash
   pytest
   ```

5. **Run the pipeline:**

   ```bash
   python main.py --dry-run   # logs what would happen, writes nothing to Notion
   python main.py             # the real thing
   python digest.py --period daily    # or --period weekly
   python feedback.py         # correct a recent classification
   ```

   Check `logs/agent_log.md` after a run, or the "Email Agent — Latest Run"
   page in Notion. Local state lives in `data/email_agent.db` (SQLite) —
   safe to delete if you want a clean rebuild; it's rebuilt from Gmail on
   the next run.
