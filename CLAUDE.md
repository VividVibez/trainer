# CLAUDE.md — Working context for the Trainer app

This file is the project's memory. Read it before changing anything. It captures
the architecture, the decisions that are already locked, the working conventions,
and the gotchas that have actually bitten. (`README.md` = human quickstart;
`DEPLOY.md` = deploy runbook.)

## What this is

A self-hosted, **planning-only** climbing training planner (PWA), single user, on
a Raspberry Pi. It does **not** log workouts — Hevy owns logging; never rebuild
that. The app shows a periodised plan week by week and lets the user keep multiple
fully independent plans and switch between them.

Stack: Flask + Flask-SQLAlchemy + SQLite (`trainer.db`), served by Gunicorn (2
workers, `127.0.0.1:8000`) behind Nginx, run by systemd unit `trainer.service`.
App factory pattern (`create_app` in `app.py`); `db` lives in `extensions.py` to
avoid circular imports.

## Data model (`models.py`)

- **Plan** — one self-contained plan. `key` (unique, stable id from the file),
  `name`, `weeks`, `count_mode` (`"parity"`), `count_odd`/`count_even` (centre
  sessions on odd/even weeks), `toggle_options` (csv, e.g. `"3,4"`), `order_index`.
- **Phase** — `plan_id`, `slug` (unique *within a plan*), `name`, `header_label`,
  `subtitle`, `week_start`/`week_end`, `order_index`, `color`, `goal`, `overview`,
  `deload_note`.
- **Week** — surrogate `id` PK; `(plan_id, week_number)` unique; `phase_id`;
  `is_deload`; `expected_sessions` (parity default); `planned_sessions` (toggle
  override, NULL = use expected). `.session_count` returns the effective value.
- **Session** — `plan_id`, `phase_id` (**NULL = the plan-global Push session**,
  appears every week), `type_letter` (A/B/C/D/P), `name`, `location`, `duration`,
  `cns_level`, `session_rules`, `order_index`, `count_four`, `count_three`.
- **Exercise** — a **shared global pool**, NOT plan-scoped. `name` is **unique**
  (the identity key). Phase variants are *separate rows* (e.g. "Max Hangs –
  Strength" vs "Density Hangs – Base"). `variant_label`, `kind`, `detail`, tags.
- **SessionExercise** — ordered link (`session_id`, `exercise_id`, `position`,
  `is_locked`). `is_locked` pins warm-ups/cool-downs.
- **Tag**, **DayAssignment**, **Setting**.
  - DayAssignment scopes to a plan via `week_id` (`week_id`, `session_id`,
    `day_index` 1–7 or NULL=tray, `is_done`, `position`). Each plan keeps its own
    placements.
  - Setting is a shared key/value store. Keys: `plan_start_date`, `active_plan_key`.

### Locked design decisions (do not relitigate without reason)

1. **Plans are completely independent** — different length, phases, counts. Defined
   entirely by an uploaded file. Backend supports an arbitrary number of plans with
   no code change; the UI just lists whatever exists.
2. **Exercises are a shared pool keyed by name.** Plans reference exercises by name.
   Uploading exercises appends; duplicates are rejected **by name**.
3. **No versioning. All edits apply globally and immediately** to the preset.
   Reordering a session's exercises, etc. changes that session on every week it
   appears. There is no per-week copy of a session's exercises.
4. **Active plan** is stored in `Setting('active_plan_key')`. Everything in the
   planner is scoped to it.
5. **Shared start date** (`Setting('plan_start_date')`) drives the current week for
   *whatever* plan is active; it is clamped to that plan's length. Switching to a
   shorter plan clamps a too-high week to that plan's last week.
6. **The 3/4 toggle is data-driven.** Each Session carries `count_four`/`count_three`;
   the Plan carries the parity rule + allowed toggle values. The model: centre
   sessions (A/B/C) sum to 4 (odd weeks) / 3 (even); plus two home (D) sessions that
   backfill so the non-Push total is a constant 5 every week; Push (P) is global, ×2.
   Seed sanity-checks this per phase (centre 4/3 · total 5/5).

## Plan / exercise JSON format

`seed/io.py` is the single source of truth for import/export. Two documents:

- `{"format":"trainer-exercises","version":1,"tags":[...],"exercises":[{name,
  variant_label,kind,detail,tags}]}`
- `{"format":"trainer-plan","version":1,"plan":{key,name,weeks,
  session_count:{mode:"parity",odd,even}, toggle_options,deload_weeks,
  phases:[{slug,name,header_label,subtitle,week_start,week_end,order_index,color,
  goal,overview,deload_note}], sessions:[{phase(null=Push),type,name,location,
  duration,cns,rules,order_index,count_four,count_three,
  exercises:[{name,locked}]}]}}`

Sessions reference exercises **by name** — every referenced name must already exist
in the pool. Validation (`validate_plan`) runs **before** any delete: it checks the
format, that phases tile `1..weeks` with no gaps, and that all referenced exercises
exist. `load_plan` creates-or-overwrites by `key` and wipes only that plan's day
placements. `export_plan` / `export_exercises` round-trip exactly.

> The authoritative, athlete-facing version of this spec lives in the **plan-
> generation project** (`PLAN_FORMAT.md`). Keep the two in sync if the format changes.

## How the app boots

`python -m seed.seed`: `drop_all` → `create_all` → `load_exercises(data/exercises.json)`
→ `load_plan(data/plan-1.json)` → `set_active_plan("plan-1")` → set
`plan_start_date`. The Python seed modules `seed/phases.py`, `seed/sessions.py`,
`seed/exercises.py` are **retired and deleted** — plan data lives in JSON now. Do
not reintroduce them.

## Conventions (follow these)

- **Strictly incremental.** One debuggable change at a time. Sandbox-test against
  Flask's test client (`create_app().test_client()`, seed, hit `/status` + the
  endpoints, assert) **before** deploying.
- **Code-only vs schema change.** A change with no `models.py` schema edit is
  code-only: deploy = pull + restart, the DB is untouched, day placements survive.
  A schema change requires `seed.seed` (drop/recreate), which **wipes day
  placements** — call this out loudly when proposing one.
- **`static/css/app.css` is ONE shared global stylesheet.** New component classes
  MUST be collision-checked against existing names before use. Already taken (not
  exhaustive): `.badge` (a 28×28px square for the A/B/C/D/P session-type chips —
  do **not** reuse it for pills; the settings "Active" pill is `.active-badge`),
  `.btn`, `.nav-btn`, `.tab`, `.count`, `.sec-label`, `.dot`, `.pad`. Namespace new
  components (`sd-*` for session detail, `set-*`/`plan-*` for settings, `ex`/`ex-*`
  for exercise rows, etc.). Grep the file first.
- **Sticky headers** must use a **solid** background (`var(--bg)`) **plus**
  `transform: translateZ(0)` (own compositing layer) or scrolling content bleeds
  through. Both `.wk-head` and `.set-head` and `.sd-head` follow this.
- **CSS cache-busting is automatic.** `app.py` has an `inject_asset_version` context
  processor exposing `asset_v(filename)` = file mtime; `base.html` links
  `app.css?v={{ asset_v('css/app.css') }}`. So a CSS change shows on a **normal**
  refresh. Don't add manual version strings.
- **Phone reliability over fancy interactions.** Tap-to-assign and ↑/↓ reorder
  arrows are used instead of drag-and-drop throughout (it's a phone PWA).
- **Deletes are explicit, not cascade-reliant.** SQLite FK cascade isn't trusted;
  `_delete_plan` tears things down in order. Keep that pattern.

## Gotchas that have actually bitten

- **Zombie gunicorn / stale workers.** Always manage via
  `sudo systemctl {start,stop,restart} trainer.service`. Right after a restart, old
  workers can briefly serve stale code → a transient 500 (especially if a route was
  removed or `base.html` changed). It self-clears as workers cycle; if it sticks or
  a process is bound to `0.0.0.0:8000`, `sudo pkill -9 -f gunicorn` then
  `sudo systemctl start trainer.service`. Health probe: `curl -s localhost:8000/status`.
- **`/status`** (not `/`) is the canonical post-deploy check: reports `plans`,
  `active_plan`, and counts.
- **Don't ever commit or delete `trainer.db`.** It's the live placements / active
  plan / start date. Recreated only by an intentional `seed.seed`.

## Pi / environment

- Host `pi-hole`; LAN `192.168.1.142`; WireGuard `10.73.213.1`. SSH user `admin`,
  key `~/.ssh/id_ed25519`. SSH aliases: `pihole` (LAN), `pihole-vpn` (VPN).
- App dir `~/trainer` with its own `venv`. `trainer.pi` resolves via `/etc/hosts`
  (the Pi-hole `dns.hosts` entry does **not** survive an FTL restart, so `/etc/hosts`
  is the reliable path).
- Dev client is Windows/PowerShell.

## Roadmap

- **Done & deployed:** multi-plan data model; Settings (switch/duplicate/delete/
  export/upload with dry-run); CSS fixes + cache-busting.
- **Built, deploy via this repo:** Stage 3 session detail (collapsible exercises,
  Reorganise mode with ↑/↓, reorder persists to `SessionExercise.position`).
- **Next:** Stage 4 — Exercise Dictionary (editable, tags, search/filter; phase
  variants as separate entries) + Session Library (editable presets, add/reorder).
- **Then:** Stage 5 — Phases Overview + PWA polish (manifest, service worker,
  home-screen install). (Editable start date already shipped in Settings.)
- Minor: make unassigned tray cards also open session detail (only placed cards
  link today). Pi housekeeping: enable unattended-upgrades; drop a duplicate
  port-53 wg0 UFW rule.
