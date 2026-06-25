"""
Bootstrap the database from the bundled JSON (seed/data/).

Plan data now lives as JSON, not Python — this loads the shared exercise pool
and the initial plan(s) through the same importer used for uploads, so the
bootstrap path and the upload path can't drift.

    python -m seed.seed            # drop + rebuild from seed/data/

⚠️  Drops the DB. Planning state only (Hevy owns the real log), so a clean
    rebuild is safe while iterating.
"""
import json
import os

from app import create_app
from extensions import db
from models import (Plan, Week, Session, Exercise, Tag, SessionExercise, Setting)
from seed.io import load_exercises, load_plan, set_active_plan

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PLAN_START_DEFAULT = "2026-06-15"          # editable in Settings; current week derives from it
BUNDLED_PLANS = ["plan-1.json"]            # add more files here to ship more starter plans
ACTIVE_DEFAULT = "plan-1"


def _load(name):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def run():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        ex_result = load_exercises(_load("exercises.json"))

        plans = []
        for fname in BUNDLED_PLANS:
            plans.append(load_plan(_load(fname)))

        set_active_plan(ACTIVE_DEFAULT)
        db.session.add(Setting(key="plan_start_date", value=PLAN_START_DEFAULT))
        db.session.commit()

        _summary(ex_result, plans)
        _sanity_checks()


def _summary(ex_result, plans):
    print("\nBootstrap complete.")
    print(f"  Exercises : {Exercise.query.count()}  "
          f"(added {len(ex_result['added'])}, skipped {len(ex_result['skipped'])})")
    print(f"  Tags      : {Tag.query.count()}")
    print(f"  Plans     : {Plan.query.count()}  -> {[p.key for p in plans]}")
    for p in plans:
        nph = len([x for x in p.phases])
        nse = Session.query.filter_by(plan_id=p.id).count()
        nwk = Week.query.filter_by(plan_id=p.id).count()
        ndl = Week.query.filter_by(plan_id=p.id, is_deload=True).count()
        nlk = (SessionExercise.query.join(Session)
               .filter(Session.plan_id == p.id).count())
        print(f"    [{p.key}] '{p.name}': {nph} phases, {nwk} weeks "
              f"({ndl} deloads), {nse} sessions, {nlk} links")


def _sanity_checks():
    """Per active-style check: centre (A/B/C) sum to 4/3 and non-Push total
    (centre + home D) sum to 5/5 in every phase of every plan."""
    print("\nPer-phase counts (centre 4/3 · non-Push total 5/5):")
    ok = True
    for plan in Plan.query.order_by(Plan.order_index):
        print(f"  Plan [{plan.key}]")
        for ph in sorted(plan.phases, key=lambda x: x.order_index):
            sessions = Session.query.filter_by(plan_id=plan.id, phase_id=ph.id).all()
            c4 = sum(s.count_four for s in sessions if s.type_letter in "ABC")
            c3 = sum(s.count_three for s in sessions if s.type_letter in "ABC")
            p4 = sum(s.count_four for s in sessions if s.type_letter != "P")
            p3 = sum(s.count_three for s in sessions if s.type_letter != "P")
            bad = not (c4 == 4 and c3 == 3 and p4 == 5 and p3 == 5)
            ok = ok and not bad
            print(f"    {ph.header_label:<18} centre {c4}/{c3} · total {p4}/{p3}"
                  f"{'  <-- MISMATCH' if bad else ''}")
        push = Session.query.filter_by(plan_id=plan.id, phase_id=None).first()
        print(f"    Push (every week)  ×{push.count_four if push else '?'}")
    print("  -> consistent" if ok else "  -> FIX NEEDED")


if __name__ == "__main__":
    run()
