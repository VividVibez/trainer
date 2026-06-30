"""
Settings blueprint — the plan-management surface.

Switch the active plan, fork (duplicate) a plan, delete one, export the
round-trip JSON, and edit the shared plan start date. File upload (with a
dry-run preview) lands in the next step; this step covers everything that needs
no file handling.
"""
import datetime
import json

from flask import (Blueprint, render_template, request, redirect, url_for,
                   Response, abort, jsonify)

from extensions import db
from models import Plan, Week, Session, Exercise, SessionExercise, DayAssignment, Setting, exercise_tags
from seed.io import (get_active_plan, set_active_plan, export_plan,
                     export_exercises, delete_plan, duplicate_plan,
                     load_plan, load_exercises, preview_plan, preview_exercises,
                     PlanImportError)

bp = Blueprint("settings", __name__)


def _plan_or_404(key):
    p = Plan.query.filter_by(key=(key or "").strip()).first()
    if p is None:
        abort(404)
    return p


def _placements(plan):
    return (DayAssignment.query.join(Week)
            .filter(Week.plan_id == plan.id, DayAssignment.day_index.isnot(None))
            .count())


def _download(doc, filename):
    body = json.dumps(doc, ensure_ascii=False, indent=2)
    return Response(body, mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# --------------------------------------------------------------------------- page
@bp.get("/settings")
def settings():
    active = get_active_plan()
    all_plans = Plan.query.order_by(Plan.order_index, Plan.id).all()
    start = db.session.get(Setting, "plan_start_date")

    def _row(p):
        return {
            "key": p.key, "name": p.name, "weeks": p.weeks,
            "phases": len(p.phases),
            "sessions": Session.query.filter_by(plan_id=p.id).count(),
            "placed": _placements(p),
            "active": bool(active and p.key == active.key),
            "archived": bool(p.is_archived),
        }

    live_plans = [_row(p) for p in all_plans if not p.is_archived]
    archived_plans = [_row(p) for p in all_plans if p.is_archived]
    return render_template("settings.html", active="settings",
                           plans=live_plans, plan_count=len(live_plans),
                           archived_plans=archived_plans,
                           exercise_count=Exercise.query.count(),
                           start_date=(start.value if start else ""))


# --------------------------------------------------------------------------- actions
@bp.post("/settings/active")
def set_active():
    p = _plan_or_404(request.form.get("key"))
    set_active_plan(p.key)
    return redirect(url_for("settings.settings"))


@bp.post("/settings/duplicate")
def duplicate():
    src = _plan_or_404(request.form.get("key"))
    name = (request.form.get("name") or "").strip() or f"{src.name} (copy)"
    duplicate_plan(src, name)
    return redirect(url_for("settings.settings"))


@bp.post("/settings/delete")
def delete():
    p = _plan_or_404(request.form.get("key"))
    active = get_active_plan()
    if Plan.query.count() <= 1:
        abort(400)                              # can't delete the only plan
    if active and p.key == active.key:
        abort(400)                              # switch away first
    delete_plan(p)
    return redirect(url_for("settings.settings"))


@bp.post("/settings/archive")
def archive():
    p = _plan_or_404(request.form.get("key"))
    active = get_active_plan()
    if active and p.key == active.key:
        abort(400)                              # can't archive the active plan
    p.is_archived = True
    db.session.commit()
    return redirect(url_for("settings.settings"))


@bp.post("/settings/restore")
def restore():
    p = _plan_or_404(request.form.get("key"))
    p.is_archived = False
    db.session.commit()
    return redirect(url_for("settings.settings"))


@bp.post("/settings/start-date")
def start_date():
    val = (request.form.get("date") or "").strip()
    try:
        datetime.date.fromisoformat(val)
    except ValueError:
        abort(400)
    s = db.session.get(Setting, "plan_start_date")
    if s is None:
        db.session.add(Setting(key="plan_start_date", value=val))
    else:
        s.value = val
    db.session.commit()
    return redirect(url_for("settings.settings"))


# --------------------------------------------------------------------------- export
@bp.get("/settings/export/exercises")
def export_ex():
    return _download(export_exercises(), "exercises.json")


@bp.get("/settings/export/plan/<key>")
def export_pl(key):
    p = _plan_or_404(key)
    return _download(export_plan(p), f"{p.key}.json")


# --------------------------------------------------------------------------- upload (dry-run + commit)
def _json_body():
    """Parse the uploaded JSON body, or (None, error-response) if unreadable."""
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return None, jsonify(ok=False, error="Couldn't read that file as JSON.")
    return data, None


@bp.post("/settings/plan/preview")
def plan_preview():
    data, err = _json_body()
    if err:
        return err
    try:
        return jsonify(ok=True, summary=preview_plan(data))
    except PlanImportError as e:
        return jsonify(ok=False, error=str(e))


@bp.post("/settings/plan/import")
def plan_import():
    data, err = _json_body()
    if err:
        return err
    try:
        plan = load_plan(data)
        return jsonify(ok=True, key=plan.key, name=plan.name)
    except PlanImportError as e:
        return jsonify(ok=False, error=str(e))


@bp.post("/settings/exercises/preview")
def exercises_preview():
    data, err = _json_body()
    if err:
        return err
    try:
        return jsonify(ok=True, summary=preview_exercises(data))
    except PlanImportError as e:
        return jsonify(ok=False, error=str(e))


@bp.post("/settings/exercises/import")
def exercises_import():
    data, err = _json_body()
    if err:
        return err
    mode = request.args.get("mode", "skip")
    try:
        res = load_exercises(data, update_existing=(mode == "overwrite"))
        return jsonify(ok=True, added=len(res["added"]), skipped=len(res["skipped"]))
    except PlanImportError as e:
        return jsonify(ok=False, error=str(e))


@bp.post("/settings/exercises/clear")
def exercises_clear():
    SessionExercise.query.delete(synchronize_session=False)
    db.session.execute(exercise_tags.delete())
    Exercise.query.delete(synchronize_session=False)
    db.session.commit()
    return redirect(url_for("settings.settings"))
