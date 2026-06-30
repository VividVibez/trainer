"""
Week Planner blueprint (plan-aware).

Owns the home page (dated week view), the 3/4 toggle, and tap-to-assign /
tick-done. Everything is scoped to the ACTIVE plan (Setting 'active_plan_key');
each plan keeps its own weeks and day placements, so switching plans in Settings
swaps the whole board. Available sessions for a week are materialised lazily as
DayAssignment rows and reconciled against the toggle every render.
"""
from collections import Counter, defaultdict

from flask import Blueprint, render_template, redirect, url_for, request, jsonify

from extensions import db
from models import Week, Session, DayAssignment, Setting
from seed.io import get_active_plan
import planweek as pw

bp = Blueprint("planner", __name__)


# --------------------------------------------------------------------------- helpers
def _plan_start():
    s = db.session.get(Setting, "plan_start_date")
    return pw.parse_start(s.value if s else None)


def _week(plan, n):
    return Week.query.filter_by(plan_id=plan.id, week_number=n).first()


def _target_counts(week):
    """{session_id: desired_count} for this week under its active toggle —
    scoped to this week's plan (phase sessions + the plan-global Push)."""
    toggle = week.session_count
    sessions = (Session.query.filter_by(plan_id=week.plan_id, phase_id=week.phase_id).all()
                + Session.query.filter_by(plan_id=week.plan_id, phase_id=None).all())
    counts = Counter()
    for s in sessions:
        counts[s.id] += s.count_four if toggle == 4 else s.count_three
    return counts


def _primary_target_count(week):
    """Non-Push (A/B/C/D) sessions this week schedules — the constant the delta
    compares 'done' against (5 under the centre + home-backfill model)."""
    toggle = week.session_count
    sessions = Session.query.filter_by(plan_id=week.plan_id, phase_id=week.phase_id).all()
    return sum((s.count_four if toggle == 4 else s.count_three)
               for s in sessions if s.type_letter != "P")


def _reconcile(week):
    """Add/remove DayAssignment rows so they match the target multiset, keyed by
    week_id. Removal prefers unassigned & not-done rows so state is preserved."""
    target = _target_counts(week)
    existing = defaultdict(list)
    for a in DayAssignment.query.filter_by(week_id=week.id).all():
        existing[a.session_id].append(a)

    changed = False
    for sid, rows in list(existing.items()):
        if sid not in target:
            for a in rows:
                db.session.delete(a)
            changed = True

    for sid, want in target.items():
        have = existing.get(sid, [])
        if len(have) < want:
            for _ in range(want - len(have)):
                db.session.add(DayAssignment(week_id=week.id, session_id=sid,
                                             day_index=None, is_done=False, position=0))
            changed = True
        elif len(have) > want:
            order = sorted(have, key=lambda a: (a.is_done, a.day_index is not None))
            for a in order[:len(have) - want]:
                db.session.delete(a)
            changed = True

    if changed:
        db.session.commit()


def _progress_delta(plan, current_week):
    """Non-Push sessions ticked done minus those scheduled, across weeks BEFORE
    the current one, within this plan. Push excluded."""
    prior = Week.query.filter(Week.plan_id == plan.id,
                              Week.week_number < current_week).all()
    expected = sum(_primary_target_count(w) for w in prior)
    done = (db.session.query(DayAssignment)
            .join(Week, DayAssignment.week_id == Week.id)
            .join(Session, DayAssignment.session_id == Session.id)
            .filter(Week.plan_id == plan.id,
                    Week.week_number < current_week,
                    DayAssignment.is_done.is_(True),
                    Session.type_letter != "P")
            .count())
    return {"value": done - expected, "done": done, "expected": expected}


# --------------------------------------------------------------------------- views
@bp.get("/")
def home():
    plan = get_active_plan()
    start = _plan_start()
    days_left = pw.days_until_start(start)
    if days_left > 0:
        mon = pw.anchor_monday(start)
        date_label = f"{pw.DOW[mon.weekday()]} {pw.ordinal(mon.day)} {pw.MONTHS[mon.month - 1]}"
        return render_template("planner.html", plan=plan,
                               not_started=True, days_until=days_left,
                               start_label=date_label)
    n = pw.current_week_number(start, total=plan.weeks)
    return redirect(url_for("planner.week_view", n=n))


@bp.get("/week/<int:n>")
def week_view(n):
    plan = get_active_plan()
    n = max(1, min(plan.weeks, n))
    start = _plan_start()
    today_week = pw.current_week_number(start, total=plan.weeks)

    week = _week(plan, n)
    _reconcile(week)

    rows = (DayAssignment.query.filter_by(week_id=week.id)
            .order_by(DayAssignment.position, DayAssignment.id).all())
    tray, by_day = [], defaultdict(list)
    for a in rows:
        (by_day[a.day_index] if a.day_index else tray).append(a)
    tray.sort(key=lambda a: (a.session.order_index, a.id))

    days = pw.week_days(start, n)
    for d in days:
        d["assignments"] = by_day.get(d["index"], [])

    return render_template(
        "planner.html",
        plan=plan,
        week=week,
        phase=week.phase,
        days=days,
        tray=tray,
        range_label=pw.week_range_label(start, n),
        today_week=today_week,
        is_current=(n == today_week),
        prev_n=n - 1 if n > 1 else None,
        next_n=n + 1 if n < plan.weeks else None,
        delta=_progress_delta(plan, today_week),
        active_phase_color=week.phase.color,
    )


# --------------------------------------------------------------------------- api
@bp.post("/api/week/<int:n>/toggle")
def api_toggle(n):
    plan = get_active_plan()
    data = request.get_json(silent=True) or {}
    want = data.get("sessions")
    if want not in plan.toggle_values:
        return jsonify(ok=False, error=f"sessions must be one of {plan.toggle_values}"), 400
    week = _week(plan, n)
    if week is None:
        return jsonify(ok=False, error="no such week"), 404
    week.planned_sessions = None if want == week.expected_sessions else want
    db.session.commit()
    _reconcile(week)
    return jsonify(ok=True, sessions=week.session_count)


def _assignment_or_404(aid):
    return db.session.get(DayAssignment, aid)


@bp.post("/api/assignment/<int:aid>/day")
def api_assign_day(aid):
    a = _assignment_or_404(aid)
    if a is None:
        return jsonify(ok=False, error="no such assignment"), 404
    data = request.get_json(silent=True) or {}
    day = data.get("day_index")
    if day is not None and day not in range(1, 8):
        return jsonify(ok=False, error="day_index must be 1..7 or null"), 400
    a.day_index = day
    db.session.commit()
    return jsonify(ok=True)


@bp.post("/api/assignment/<int:aid>/unassign")
def api_unassign(aid):
    a = _assignment_or_404(aid)
    if a is None:
        return jsonify(ok=False, error="no such assignment"), 404
    a.day_index = None
    db.session.commit()
    return jsonify(ok=True)


@bp.post("/api/assignment/<int:aid>/done")
def api_done(aid):
    a = _assignment_or_404(aid)
    if a is None:
        return jsonify(ok=False, error="no such assignment"), 404
    data = request.get_json(silent=True) or {}
    a.is_done = bool(data.get("done"))
    db.session.commit()
    plan = get_active_plan()
    start = _plan_start()
    return jsonify(ok=True,
                   delta=_progress_delta(plan, pw.current_week_number(start, total=plan.weeks)))
