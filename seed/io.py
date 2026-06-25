"""Import / export of the portable plan + exercise JSON.

The single source of truth for plan data. Importing a plan file creates or
overwrites a plan by key (wiping only that plan's day placements); importing an
exercise file appends to the shared pool (duplicates rejected by name). Both
round-trip via the matching export_* functions.
"""
from extensions import db
from models import (Plan, Phase, Week, Session, Exercise, SessionExercise,
                    Tag, DayAssignment)
import re

FORMAT_VERSION = 1


class PlanImportError(Exception):
    """Raised when an uploaded file is malformed or references missing data."""


# --------------------------------------------------------------------------- tags
def _tag(name, cache):
    t = cache.get(name)
    if t is None:
        t = Tag.query.filter_by(name=name).first() or Tag(name=name)
        db.session.add(t)
        cache[name] = t
    return t


# --------------------------------------------------------------------------- exercises
def load_exercises(data, *, update_existing=False):
    """Append exercises to the shared pool. By default duplicates (by name) are
    skipped and reported; update_existing=True overwrites their detail/tags."""
    if data.get("format") != "trainer-exercises":
        raise PlanImportError("not an exercises file (expected format 'trainer-exercises')")
    cache = {t.name: t for t in Tag.query.all()}
    added, updated, skipped = [], [], []
    for e in data.get("exercises", []):
        name = (e.get("name") or "").strip()
        if not name:
            raise PlanImportError("an exercise is missing a name")
        existing = Exercise.query.filter_by(name=name).first()
        if existing and not update_existing:
            skipped.append(name)
            continue
        ex = existing or Exercise(name=name)
        ex.variant_label = e.get("variant_label")
        ex.kind = e.get("kind", "main")
        ex.detail = e.get("detail", "")
        ex.tags = [_tag(t, cache) for t in e.get("tags", [])]
        if existing:
            updated.append(name)
        else:
            db.session.add(ex)
            added.append(name)
    for t in data.get("tags", []):           # preserve standalone tag vocabulary
        _tag(t, cache)
    db.session.commit()
    return {"added": added, "updated": updated, "skipped": skipped}


# --------------------------------------------------------------------------- plan
def _delete_plan(plan):
    """Tear down a plan and everything under it (explicit, order-correct, so it
    doesn't depend on SQLite cascade being enabled)."""
    wids = [w.id for w in Week.query.filter_by(plan_id=plan.id)]
    if wids:
        DayAssignment.query.filter(DayAssignment.week_id.in_(wids)).delete(synchronize_session=False)
    sids = [s.id for s in Session.query.filter_by(plan_id=plan.id)]
    if sids:
        SessionExercise.query.filter(SessionExercise.session_id.in_(sids)).delete(synchronize_session=False)
    Session.query.filter_by(plan_id=plan.id).delete(synchronize_session=False)
    Week.query.filter_by(plan_id=plan.id).delete(synchronize_session=False)
    Phase.query.filter_by(plan_id=plan.id).delete(synchronize_session=False)
    db.session.delete(plan)
    db.session.flush()


def validate_plan(data):
    """Cheap structural validation; raises PlanImportError on problems. Returns
    the inner plan dict. Also surfaces unknown exercise references and week gaps
    so import can fail loudly *before* deleting the old plan."""
    if data.get("format") != "trainer-plan":
        raise PlanImportError("not a plan file (expected format 'trainer-plan')")
    p = data.get("plan") or {}
    for field in ("key", "name", "weeks", "phases", "sessions"):
        if field not in p:
            raise PlanImportError(f"plan is missing '{field}'")
    weeks = int(p["weeks"])
    # phases must tile 1..weeks with no gaps
    covered = set()
    for ph in p["phases"]:
        covered |= set(range(ph["week_start"], ph["week_end"] + 1))
    gaps = sorted(set(range(1, weeks + 1)) - covered)
    if gaps:
        raise PlanImportError(f"weeks not covered by any phase: {gaps[:10]}"
                              f"{'…' if len(gaps) > 10 else ''}")
    # every referenced exercise must already exist in the pool
    pool = {e.name for e in Exercise.query.all()}
    missing = sorted({x["name"] for s in p["sessions"] for x in s.get("exercises", [])
                      if x["name"] not in pool})
    if missing:
        raise PlanImportError(f"plan references {len(missing)} exercise(s) not in the "
                              f"pool — import those first: {missing[:5]}"
                              f"{'…' if len(missing) > 5 else ''}")
    return p


def load_plan(data):
    """Create or overwrite a plan by key. Validates first; wipes only this
    plan's data (other plans untouched). Returns the new Plan."""
    p = validate_plan(data)
    key = p["key"]
    pool = {e.name: e for e in Exercise.query.all()}

    existing = Plan.query.filter_by(key=key).first()
    order_index = existing.order_index if existing else Plan.query.count()
    if existing:
        _delete_plan(existing)

    sc = p.get("session_count", {})
    plan = Plan(
        key=key, name=p["name"], weeks=int(p["weeks"]),
        count_mode=sc.get("mode", "parity"),
        count_odd=int(sc.get("odd", 4)), count_even=int(sc.get("even", 3)),
        toggle_options=",".join(str(t) for t in p.get("toggle_options", [3, 4])),
        order_index=order_index,
    )
    db.session.add(plan)
    db.session.flush()

    phases = {}
    for ph in p["phases"]:
        obj = Phase(plan_id=plan.id, slug=ph["slug"], name=ph["name"],
                    header_label=ph["header_label"], subtitle=ph.get("subtitle"),
                    week_start=ph["week_start"], week_end=ph["week_end"],
                    order_index=ph["order_index"], color=ph["color"],
                    goal=ph.get("goal"), overview=ph.get("overview"),
                    deload_note=ph.get("deload_note"))
        db.session.add(obj)
        phases[ph["slug"]] = obj
    db.session.flush()

    deloads = set(p.get("deload_weeks", []))
    for wk in range(1, plan.weeks + 1):
        ph = next(o for o in phases.values() if o.week_start <= wk <= o.week_end)
        db.session.add(Week(plan_id=plan.id, week_number=wk, phase_id=ph.id,
                            is_deload=wk in deloads,
                            expected_sessions=plan.count_odd if wk % 2 else plan.count_even,
                            planned_sessions=None))

    for s in p["sessions"]:
        ph = phases.get(s["phase"]) if s.get("phase") else None
        sess = Session(plan_id=plan.id, phase_id=ph.id if ph else None,
                       type_letter=s["type"], name=s["name"],
                       location=s.get("location"), duration=s.get("duration"),
                       cns_level=s.get("cns"), session_rules=s.get("rules"),
                       order_index=s.get("order_index", 0),
                       count_four=s.get("count_four", 1), count_three=s.get("count_three", 1))
        db.session.add(sess)
        db.session.flush()
        for pos, x in enumerate(s.get("exercises", []), start=1):
            db.session.add(SessionExercise(session_id=sess.id, exercise_id=pool[x["name"]].id,
                                           position=pos, is_locked=bool(x.get("locked"))))
    db.session.commit()
    return plan


# --------------------------------------------------------------------------- active plan
def set_active_plan(key):
    from models import Setting
    s = db.session.get(Setting, "active_plan_key")
    if s is None:
        db.session.add(Setting(key="active_plan_key", value=key))
    else:
        s.value = key
    db.session.commit()


def get_active_plan():
    """The active Plan, or the first by display order if the setting is unset/stale."""
    from models import Setting
    s = db.session.get(Setting, "active_plan_key")
    key = s.value if s else None
    plan = Plan.query.filter_by(key=key).first() if key else None
    return plan or Plan.query.order_by(Plan.order_index, Plan.id).first()


# --------------------------------------------------------------------------- export
def export_exercises():
    return {
        "format": "trainer-exercises", "version": FORMAT_VERSION,
        "tags": sorted(t.name for t in Tag.query.all()),
        "exercises": [{
            "name": e.name, "variant_label": e.variant_label, "kind": e.kind,
            "detail": e.detail, "tags": sorted(t.name for t in e.tags),
        } for e in Exercise.query.order_by(Exercise.id)],
    }


def export_plan(plan):
    weeks = Week.query.filter_by(plan_id=plan.id).order_by(Week.week_number).all()
    phases = [{
        "slug": p.slug, "name": p.name, "header_label": p.header_label,
        "subtitle": p.subtitle, "week_start": p.week_start, "week_end": p.week_end,
        "order_index": p.order_index, "color": p.color,
        "goal": p.goal, "overview": p.overview, "deload_note": p.deload_note,
    } for p in Phase.query.filter_by(plan_id=plan.id).order_by(Phase.order_index)]

    def skey(s):
        return (s.phase.order_index if s.phase else 999, s.order_index, s.id)

    sessions = []
    for s in sorted(Session.query.filter_by(plan_id=plan.id).all(), key=skey):
        sessions.append({
            "phase": s.phase.slug if s.phase else None,
            "type": s.type_letter, "name": s.name,
            "location": s.location, "duration": s.duration, "cns": s.cns_level,
            "rules": s.session_rules, "order_index": s.order_index,
            "count_four": s.count_four, "count_three": s.count_three,
            "exercises": [{"name": l.exercise.name, "locked": bool(l.is_locked)}
                          for l in sorted(s.exercises, key=lambda x: x.position)],
        })

    return {"format": "trainer-plan", "version": FORMAT_VERSION, "plan": {
        "key": plan.key, "name": plan.name, "weeks": plan.weeks,
        "session_count": {"mode": plan.count_mode, "odd": plan.count_odd, "even": plan.count_even},
        "toggle_options": plan.toggle_values,
        "deload_weeks": [w.week_number for w in weeks if w.is_deload],
        "phases": phases, "sessions": sessions,
    }}


# --------------------------------------------------------------------------- manage
def _slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "plan"


def _unique_key(base):
    key, i = base, 2
    while Plan.query.filter_by(key=key).first():
        key = f"{base}-{i}"
        i += 1
    return key


def delete_plan(plan):
    """Remove a plan and everything under it. (Caller guards against deleting the
    active or the last remaining plan.)"""
    _delete_plan(plan)
    db.session.commit()


def duplicate_plan(source, new_name):
    """Fork a plan: same phases/sessions/counts under a new key, with a fresh
    (empty) day board. Edit the copy and switch to it without touching the
    original."""
    doc = export_plan(source)
    doc["plan"]["name"] = new_name
    doc["plan"]["key"] = _unique_key(_slugify(new_name))
    return load_plan(doc)


# --------------------------------------------------------------------------- preview (dry-run)
def preview_exercises(data):
    """What load_exercises WOULD do, without writing. Raises on bad format."""
    if data.get("format") != "trainer-exercises":
        raise PlanImportError("not an exercises file (expected format 'trainer-exercises')")
    existing = {e.name for e in Exercise.query.all()}
    seen, added, dupes = set(), [], []
    for e in data.get("exercises", []):
        name = (e.get("name") or "").strip()
        if not name:
            raise PlanImportError("an exercise is missing a name")
        if name in existing or name in seen:
            dupes.append(name)
        else:
            added.append(name)
            seen.add(name)
    return {"total": len(data.get("exercises", [])), "added": added, "skipped": dupes}


def preview_plan(data):
    """What load_plan WOULD do, without writing. validate_plan raises loudly on
    any problem (bad format, week gaps, unknown exercises)."""
    p = validate_plan(data)
    existing = Plan.query.filter_by(key=p["key"]).first()
    placements = 0
    if existing:
        placements = (DayAssignment.query.join(Week)
                      .filter(Week.plan_id == existing.id, DayAssignment.day_index.isnot(None))
                      .count())
    return {
        "key": p["key"], "name": p["name"], "weeks": int(p["weeks"]),
        "phases": len(p["phases"]), "sessions": len(p["sessions"]),
        "action": "overwrite" if existing else "create",
        "existing_name": existing.name if existing else None,
        "placements_wiped": placements,
    }
