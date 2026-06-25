# DEPLOY.md — Deploying to the Pi

The app runs on the Pi at `~/trainer` (its own venv), served by gunicorn under the
systemd unit `trainer.service`, behind Nginx. SSH alias `pihole` (LAN) or
`pihole-vpn` (WireGuard).

## One-time: make the Pi a git checkout

Do this once so future deploys are `git pull`. **Back up `trainer.db` first** — it
is your live data and is gitignored, so it must survive the switch.

```bash
ssh pihole
cd ~
cp trainer/trainer.db trainer.db.keep            # safety copy of live state
mv trainer trainer.preflight.bak                 # set the old dir aside

git clone <YOUR_REPO_URL> trainer                # fresh checkout
cd trainer
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp ~/trainer.db.keep trainer.db                  # restore live data (gitignored, stays)

# sanity check it serves, then point systemd at this dir if the path changed
venv/bin/python -c "from app import create_app; print(create_app().test_client().get('/status').get_json())"
sudo systemctl restart trainer.service
curl -s localhost:8000/status
```

If `/status` is healthy and the browser works, remove `~/trainer.preflight.bak` and
`~/trainer.db.keep`. The `trainer.service` unit runs
`venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8000 app:app` with
`WorkingDirectory=/home/admin/trainer`; leave it as-is if the path is unchanged.

## Normal deploy (after the checkout exists)

### Code-only change (no `models.py` schema edit)

Day placements and the DB are untouched.

```bash
ssh pihole
cd ~/trainer
git pull
find . -name __pycache__ -type d -exec rm -rf {} +     # clear stale bytecode
sudo systemctl restart trainer.service
curl -s localhost:8000/status                          # expect status ok + correct counts
```

CSS-only edits auto-cache-bust (mtime), so a **normal** browser refresh shows them.

### Schema change (any `models.py` edit)

**This wipes day placements** (drop + recreate from JSON). Make sure that's intended.

```bash
ssh pihole
cd ~/trainer
git pull
find . -name __pycache__ -type d -exec rm -rf {} +
venv/bin/python -m seed.seed        # drops + rebuilds trainer.db from seed/data/*.json
sudo systemctl restart trainer.service
curl -s localhost:8000/status
```

## How to tell which kind a change is

If the diff touches `models.py` (new column/table, changed PK/constraint) → schema
change → reseed. Otherwise → code-only → no reseed. When in doubt, a `git diff
models.py` answers it.

## Verifying

- `curl -s localhost:8000/status` → JSON with `status: ok`, `plans`, `active_plan`,
  and counts. This is the canonical check.
- Then load `http://trainer.pi` and click through the changed area. Wait a few
  seconds after the restart before refreshing (worker cycle).

## Troubleshooting

- **Transient 500 right after a restart** (often when a route was removed or a
  template changed): an old gunicorn worker briefly served stale code. Wait a few
  seconds and refresh; it self-clears as workers cycle.
- **Persistent 500 / stale behaviour / something bound to `0.0.0.0:8000`**: a zombie
  gunicorn. Fix:
  ```bash
  sudo pkill -9 -f gunicorn
  sudo systemctl start trainer.service
  ```
- **Always** start/stop/restart via `sudo systemctl … trainer.service` — never start
  gunicorn by hand (that's how zombies happen).
- **CSS change not showing**: it should on a normal refresh (mtime cache-bust). If
  not, confirm `app.css` actually changed on disk (`git pull` landed) and the page
  HTML shows `app.css?v=<number>` with a new number.
- **Rollback**: `git log --oneline`, then `git checkout <good-sha>` (or
  `git revert`), restart. If the bad change was a schema change, reseed after
  rolling back.

## Exporting live plans (backup of plan content, not placements)

```bash
ssh pihole
cd ~/trainer
venv/bin/python -m seed.export ~/exports     # writes exercises.json + <plan>.json
```

Useful before editing a plan, or to capture a plan that was uploaded via the UI but
isn't in `seed/data/`.
