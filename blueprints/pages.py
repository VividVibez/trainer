"""
Page routes outside the Week Planner.

session_detail (Stage 3) is the real ordered/collapsible/reorderable session view.
phases / dictionary / library remain stubs until their stages.
"""
from flask import Blueprint, render_template, abort, request, jsonify

from extensions import db
from models import Session

bp = Blueprint("pages", __name__)


@bp.get("/phases")
def phases():
    return render_template("stub.html", title="Phases Overview",
                           note="Full phase breakdown lands in Stage 5.",
                           active="phases")


@bp.get("/dictionary")
def dictionary():
    return render_template("stub.html", title="Exercise Dictionary",
                           note="Searchable, editable Dictionary lands in Stage 4.",
                           active="dictionary")


@bp.get("/library")
def library():
    return render_template("stub.html", title="Session Library",
                           note="Editable session presets land in Stage 4.",
                           active="library")


@bp.get("/session/<int:session_id>")
def session_detail(session_id):
    s = db.session.get(Session, session_id)
    if s is None:
        abort(404)
    links = sorted(s.exercises, key=lambda x: x.position)
    items = [{
        "lid": l.id,
        "name": l.exercise.name,
        "variant": l.exercise.variant_label,
        "kind": l.exercise.kind,
        "detail": l.exercise.detail,
        "tags": [t.name for t in l.exercise.tags],
        "locked": bool(l.is_locked),
    } for l in links]
    reorderable = sum(1 for it in items if not it["locked"])
    return render_template("session.html", active="plan",
                           s=s, phase=s.phase, items=items, reorderable=reorderable,
                           active_phase_color=(s.phase.color if s.phase else None))


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
