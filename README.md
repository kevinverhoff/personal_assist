# personal_assist

Hi! I'm Kevin's personal assistant!

This repo is the first real piece of that: an **Email Intelligence Agent**
for personal Gmail. It reads your inbox, classifies each message along
several independent dimensions, cross-references the sender against a
Notion knowledge base of people/organizations you actually know, prioritizes
messages from people you know, labels known senders right in Gmail (red
"VIP", yellow "Known Contact"), and archives routine mail it's confident
about — while never touching anything from someone in your People database,
and never deleting anything (archived mail just leaves the inbox; it's
still fully there in All Mail, one click to undo).

Full design rationale lives in
[`docs/superpowers/specs/2026-08-14-email-intelligence-agent-design.md`](docs/superpowers/specs/2026-08-14-email-intelligence-agent-design.md);
the task-by-task build record is in
[`docs/superpowers/plans/2026-08-14-email-intelligence-agent-phase1.md`](docs/superpowers/plans/2026-08-14-email-intelligence-agent-phase1.md).

## Where things stand

**Phase 1 is fully built and mostly verified against real Gmail, Gemini,
and Notion data** — not just unit tests. 91 automated tests pass.

What exists today:

- `gmail_client.py` / `gmail_auth_setup.py` — Gmail ingestion scoped to
  `in:inbox`, incremental via Gmail's history API (paginated correctly —
  an earlier bug silently dropped messages past the first 100 history
  records; fixed and verified with real mail). Uses the `gmail.modify`
  scope (read + label changes only — no permanent delete, no send).
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
  The in-memory cache updates itself immediately after every write, so a
  batch with several messages from the same brand-new sender doesn't
  create a duplicate Person for each one.
- `prioritization.py` — shared grouping logic: messages from people in
  your People database first, then anything else that needs attention
  (high/critical importance or action-required), then everything else.
  Used by both the run summary and the digest, formatted compactly
  (`[type] "subject" — sender (email)`).
- `main.py` — applies a real Gmail label to every message from a sender
  matched in your People database: red **VIP** for VIP-importance people,
  yellow **Known Contact** for everyone else. (Gmail's colored "stars" are
  a Gmail-UI-only feature, not exposed via the API at all — labels are the
  closest API-controllable equivalent.) Skipped entirely on `--dry-run`.
- `archiving.py` / `main.py` — archives a message (removes the INBOX
  label, never deletes) only when it's routine (`digest_worthy`),
  high-confidence (≥ 0.9), **and** the sender does not match anyone in
  your People database. On by default; `--no-archive` opts out for a run.
  Every archived message is logged with enough detail to find and undo it.
- `store.py` — local SQLite (schema designed to be a drop-in match for
  Cloudflare D1 later).
- `agent_log.py` — a local "notepad" log plus a single Notion "Latest Run"
  status page, updated in place each run.
- `digest.py` — `python digest.py --period daily|weekly` groups routine
  mail deterministically (flagging how many of each type were archived vs.
  kept) and has Gemini phrase (never count) a summary, written to a
  dedicated Notion "Email Digests" database.
- `feedback.py` — a CLI to correct a stored classification, so accuracy
  can eventually be measured rather than eyeballed.

Everything currently runs **locally, by hand** — no scheduling yet, no
Cloudflare. That's intentional (see Phase 1b below).

### In progress

Archiving and Gmail labeling (VIP/Known Contact) are both implemented and
unit-tested, but **neither has been verified against a real Gmail call
yet** — both need a fresh OAuth consent (the `gmail.modify` scope is new;
existing refresh tokens don't have it). Re-run `python gmail_auth_setup.py`,
then a real run can be verified end to end.

### Next steps

- **Verify real archiving and labeling** (above) once re-consent is done.
- **Phase 1b**: move scheduling to GitHub Actions (cron, 4-6x/day) and
  storage to Cloudflare D1, once the local pipeline has run for a while
  and feels trustworthy. No other component changes expected — the store
  layer was written for exactly this swap.
- **v1.1**: signature/domain-based Organization and Affiliation inference
  for newly-discovered senders (deliberately deferred out of Phase 1 as
  the riskiest, least-tested piece of the design).
- Consider whether other action types (beyond archiving routine mail)
  should eventually be approval-gated rather than automatic, once
  `feedback.py` data accumulates enough to know how trustworthy the
  classifier actually is.

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
   otherwise the refresh token expires after 7 days. The scope is
   `gmail.modify` (read + label changes, used for archiving) — if you have
   an older refresh token minted before archiving existed, it does not
   carry this permission; re-run this script to get a new one.

4. **Run the tests:**

   ```bash
   pytest
   ```

5. **Run the pipeline:**

   ```bash
   python main.py --dry-run     # logs what would happen, writes nothing to Notion/Gmail
   python main.py               # the real thing — archives routine mail by default
   python main.py --no-archive  # real Notion writes, but never archives anything
   python digest.py --period daily    # or --period weekly
   python feedback.py           # correct a recent classification
   ```

   Check `logs/agent_log.md` after a run, or the "Email Agent — Latest Run"
   page in Notion — both list anything archived with its subject and
   sender so you can find and undo it in Gmail if needed (archived mail
   isn't deleted, just moved out of the inbox). Local state lives in
   `data/email_agent.db` (SQLite) — safe to delete if you want a clean
   rebuild; it's rebuilt from Gmail on the next run.
