# Trainer — Climbing Training Planner

A self-hosted, **planning-only** web app (a PWA) for laying out a periodised
bouldering plan week by week. It does **not** log workouts — Hevy does that. This
app answers "what am I doing this week, and on which day?" and lets you carry
multiple independent plans.

Runs on a Raspberry Pi on the home network / WireGuard VPN. Single user.

## Stack

- **Flask** + **Flask-SQLAlchemy** (app factory in `app.py`, `db` in `extensions.py`)
- **SQLite** (`trainer.db` in the project root — runtime state, gitignored)
- **Gunicorn** (2 workers, `127.0.0.1:8000`) behind **Nginx**, run by **systemd** (`trainer.service`)
- Vanilla HTML/CSS/JS templates (no build step). One global stylesheet: `static/css/app.css`.

## Layout

```
app.py            App factory (create_app), /status + /healthz, asset-version cache-bust
config.py         SQLite URI + flags (no secrets)
extensions.py     db = SQLAlchemy()
models.py         Plan, Phase, Week, Session, Exercise, SessionExercise, Tag, DayAssignment, Setting
planweek.py       Date math: start date -> current week, week date ranges
blueprints/
  planner.py      Home / week view, 3-4 toggle, tap-to-assign, tick-done  (all plan-scoped)
  pages.py        Session detail (+ reorder); phases/dictionary/library stubs
  settings.py     Plan switch / duplicate / delete / export / upload; start date
seed/
  io.py           Import + export + active-plan layer (the source of truth for plan data)
  seed.py         Bootstrap: drop_all/create_all, load JSON, set active plan
  export.py       CLI: python -m seed.export  -> writes exercises.json + <plan>.json
  data/           Bundled JSON the app boots from
    exercises.json   Shared exercise pool
    plan-1.json      The default 52-week plan
templates/        base.html, planner.html, session.html, settings.html, stub.html
static/css/app.css, static/js/planner.js
```

## Run locally (development)

```bash
python -m venv venv
venv/bin/pip install -r requirements.txt      # Windows: venv\Scripts\pip
venv/bin/python -m seed.seed                  # creates + seeds trainer.db
venv/bin/flask --app app run --debug          # http://127.0.0.1:5000
```

`flask run` is dev-only; production uses gunicorn (see `DEPLOY.md`). The DB is
recreated from `seed/data/*.json` by `seed.seed` — **it drops everything first**,
so only run it on a fresh DB or when you intend to reset.

## Test

There is no test framework wired up; testing is done against Flask's test client.
The pattern used throughout development:

```python
from app import create_app
c = create_app().test_client()
assert c.get("/status").get_json()["status"] == "ok"
# render pages, POST to API endpoints, assert on results
```

Always exercise changes this way **before** deploying.

## Deploy

See **`DEPLOY.md`**. In short, once the Pi is a git checkout: `git pull` →
(reseed only if the schema changed) → restart `trainer.service` → check `/status`.

## Working notes for AI agents / future-you

See **`CLAUDE.md`** — it holds the architecture decisions, conventions, and the
hard-won gotchas (the zombie-gunicorn trap, schema-change reseed rule, the shared
stylesheet collision rule, CSS cache-busting). Read it before changing anything.
