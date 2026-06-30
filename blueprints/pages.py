"""
Page routes outside the Week Planner.

session_detail (Stage 3) — collapsible exercises, reorder, Stage 4 adds add/remove.
dictionary / library — Stage 4: searchable/editable exercise pool + session presets.
phases — Stage 5 stub.
"""
from flask import Blueprint, render_template, abort, request, jsonify

from extensions import db
from models import Session, Exercise, SessionExercise, Tag, Plan, Setting

bp = Blueprint("pages", __name__)


@bp.get("/phases")
def phases():
    import planweek as pw
    from seed.io import get_active_plan
    plan = get_active_plan()
    if not plan:
        return render_template("stub.html", title="Phases Overview",
                               note="No active plan seeded yet.", active="phases")
    start_setting = db.session.get(Setting, "plan_start_date")
    start = pw.parse_start(start_setting.value if start_setting else None)
    current_week = pw.current_week_number(start, total=plan.weeks)
    phase_data = []
    for ph in sorted(plan.phases, key=lambda p: p.order_index):
        deload_weeks = [w.week_number for w in ph.weeks if w.is_deload]
        phase_data.append({
            "slug": ph.slug,
            "name": ph.name,
            "header_label": ph.header_label,
            "subtitle": ph.subtitle or "",
            "week_start": ph.week_start,
            "week_end": ph.week_end,
            "color": ph.color,
            "goal": ph.goal or "",
            "overview": ph.overview or "",
            "deload_note": ph.deload_note or "",
            "deload_weeks": deload_weeks,
            "is_current": ph.week_start <= current_week <= ph.week_end,
            "is_past": ph.week_end < current_week,
        })
    return render_template("phases.html",
                           plan=plan, phases=phase_data,
                           current_week=current_week,
                           active="phases")


@bp.get("/dictionary")
def dictionary():
    exercises = Exercise.query.order_by(Exercise.name).all()
    all_tags = Tag.query.order_by(Tag.name).all()
    ex_list = [{
        "id": e.id,
        "name": e.name,
        "variant": e.variant_label or "",
        "kind": e.kind or "main",
        "detail": e.detail or "",
        "tags": [t.name for t in e.tags],
        "tag_ids": [t.id for t in e.tags],
        "in_use": len(e.links) > 0,
    } for e in exercises]
    tag_list = [{"id": t.id, "name": t.name} for t in all_tags]
    return render_template("dictionary.html",
                           ex_list=ex_list, all_tags=tag_list,
                           active="dictionary")


@bp.get("/library")
def library():
    setting = db.session.get(Setting, "active_plan_key")
    active_key = setting.value if setting else None
    plans = Plan.query.order_by(Plan.order_index).all()
    plan_data = []
    for p in plans:
        sessions = Session.query.filter_by(plan_id=p.id).all()
        sessions.sort(key=lambda s: (s.phase.order_index if s.phase else 9999, s.order_index))
        groups = []
        for s in sessions:
            phase = s.phase
            pid = phase.id if phase else None
            if not groups or groups[-1]["phase_id"] != pid:
                groups.append({
                    "phase_id": pid,
                    "phase_name": phase.name if phase else "Global",
                    "phase_color": phase.color if phase else "#F5C842",
                    "sessions": [],
                })
            groups[-1]["sessions"].append({
                "id": s.id,
                "type": s.type_letter,
                "name": s.name,
                "location": s.location or "",
                "ex_count": len(s.exercises),
            })
        plan_data.append({
            "name": p.name,
            "key": p.key,
            "active": p.key == active_key,
            "groups": groups,
        })
    return render_template("library.html", plans=plan_data, active="library")


@bp.get("/session/<int:session_id>")
def session_detail(session_id):
    s = db.session.get(Session, session_id)
    if s is None:
        abort(404)
    links = sorted(s.exercises, key=lambda x: x.position)
    items = [{
        "lid": l.id,
        "eid": l.exercise_id,
        "name": l.exercise.name,
        "variant": l.exercise.variant_label,
        "kind": l.exercise.kind,
        "duration": l.exercise.duration,
        "detail": l.exercise.detail,
        "steps": [s for s in (l.exercise.steps or "").split("\n") if s],
        "tags": [t.name for t in l.exercise.tags],
        "locked": bool(l.is_locked),
    } for l in links]
    reorderable = sum(1 for it in items if not it["locked"])
    used_ids = {l.exercise_id for l in links}
    add_pool = [{"id": e.id, "name": e.name, "kind": e.kind or "main"}
                for e in Exercise.query.order_by(Exercise.name).all()
                if e.id not in used_ids]
    return render_template("session.html", active="plan",
                           s=s, phase=s.phase, items=items, reorderable=reorderable,
                           active_phase_color=(s.phase.color if s.phase else None),
                           add_pool=add_pool)


@bp.post("/session/<int:session_id>/reorder")
def session_reorder(session_id):
    """Persist a new order for the non-locked (middle) exercises. Locked warm-up
    / cool-down keep their slots. Edits the preset globally (no per-week copy)."""
    s = db.session.get(Session, session_id)
    if s is None:
        abort(404)
    data = request.get_json(silent=True) or {}
    new_middle = data.get("order", [])
    links = sorted(s.exercises, key=lambda x: x.position)
    middle_ids = [l.id for l in links if not l.is_locked]
    if sorted(new_middle) != sorted(middle_ids):
        return jsonify(ok=False, error="order must be a permutation of the reorderable exercises"), 400
    by_id = {l.id: l for l in links}
    nxt = iter(new_middle)
    for pos, l in enumerate(links, start=1):
        by_id[l.id if l.is_locked else next(nxt)].position = pos
    db.session.commit()
    return jsonify(ok=True)


@bp.post("/session/<int:session_id>/exercises/add")
def session_exercise_add(session_id):
    """Add an exercise from the pool to a session. Inserts before trailing locked
    cool-downs so warm-up / cool-down pinned positions are respected."""
    s = db.session.get(Session, session_id)
    if s is None:
        abort(404)
    data = request.get_json(silent=True) or {}
    ex_id = data.get("exercise_id")
    if not ex_id:
        return jsonify(ok=False, error="exercise_id required"), 400
    e = db.session.get(Exercise, ex_id)
    if e is None:
        return jsonify(ok=False, error="Exercise not found"), 404
    if any(l.exercise_id == ex_id for l in s.exercises):
        return jsonify(ok=False, error="Already in this session"), 409
    links = sorted(s.exercises, key=lambda x: x.position)
    last_non_locked = max((l.position for l in links if not l.is_locked), default=None)
    if last_non_locked is None:
        new_pos = (max((l.position for l in links), default=0)) + 1
    else:
        for l in links:
            if l.is_locked and l.position > last_non_locked:
                l.position += 1
        new_pos = last_non_locked + 1
    link = SessionExercise(session_id=session_id, exercise_id=ex_id,
                           position=new_pos, is_locked=False)
    db.session.add(link)
    db.session.commit()
    return jsonify(ok=True, lid=link.id, exercise_id=ex_id,
                   name=e.name, kind=e.kind or "main",
                   variant=e.variant_label or "",
                   duration=e.duration or "",
                   detail=e.detail or "",
                   steps=[s for s in (e.steps or "").split("\n") if s],
                   tags=[t.name for t in e.tags])


@bp.delete("/session/<int:session_id>/exercises/<int:link_id>")
def session_exercise_remove(session_id, link_id):
    """Remove a non-locked exercise from a session and compact positions."""
    link = db.session.get(SessionExercise, link_id)
    if link is None or link.session_id != session_id:
        abort(404)
    if link.is_locked:
        return jsonify(ok=False, error="Cannot remove a pinned exercise"), 403
    removed_pos = link.position
    for l in SessionExercise.query.filter_by(session_id=session_id).all():
        if l.id != link_id and l.position > removed_pos:
            l.position -= 1
    db.session.delete(link)
    db.session.commit()
    return jsonify(ok=True)


# ── Exercise CRUD ─────────────────────────────────────────────────────────────

@bp.post("/api/exercise/new")
def exercise_new():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify(ok=False, error="Name is required"), 400
    if Exercise.query.filter_by(name=name).first():
        return jsonify(ok=False, error="An exercise with this name already exists"), 409
    e = Exercise(
        name=name,
        variant_label=(data.get("variant_label") or "").strip() or None,
        kind=(data.get("kind") or "main").strip() or "main",
        detail=(data.get("detail") or "").strip() or None,
    )
    tag_ids = data.get("tag_ids") or []
    if tag_ids:
        e.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all()
    db.session.add(e)
    db.session.commit()
    return jsonify(ok=True, id=e.id, name=e.name)


@bp.post("/api/exercise/<int:ex_id>")
def exercise_update(ex_id):
    e = db.session.get(Exercise, ex_id)
    if e is None:
        abort(404)
    data = request.get_json(silent=True) or {}
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            return jsonify(ok=False, error="Name is required"), 400
        clash = Exercise.query.filter_by(name=name).first()
        if clash and clash.id != ex_id:
            return jsonify(ok=False, error="Name already taken by another exercise"), 409
        e.name = name
    if "variant_label" in data:
        e.variant_label = (data["variant_label"] or "").strip() or None
    if "kind" in data:
        e.kind = (data["kind"] or "main").strip() or "main"
    if "detail" in data:
        e.detail = (data["detail"] or "").strip() or None
    if "tag_ids" in data:
        tag_ids = data["tag_ids"] or []
        e.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all() if tag_ids else []
    db.session.commit()
    return jsonify(ok=True)


@bp.delete("/api/exercise/<int:ex_id>")
def exercise_delete(ex_id):
    e = db.session.get(Exercise, ex_id)
    if e is None:
        abort(404)
    if e.links:
        session_names = list({l.session.name for l in e.links})[:3]
        return jsonify(ok=False,
                       error=f"In use by: {', '.join(session_names)}"), 409
    db.session.delete(e)
    db.session.commit()
    return jsonify(ok=True)
