"""
Flask app factory for the climbing training planner.

Gunicorn target: ``app:app`` (the systemd service / Nginx setup point here).
Stage 2 adds the Week Planner page and stub routes for the remaining tabs;
the schema + seed are Stage 1.
"""
from flask import Flask, jsonify

from config import Config
from extensions import db


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)

    # Register models on the metadata before any query / create_all.
    from models import (  # noqa: F401
        Plan, Phase, Week, Session, Exercise, SessionExercise, Tag, DayAssignment, Setting,
    )

    # Page + API blueprints
    from blueprints.planner import bp as planner_bp
    from blueprints.pages import bp as pages_bp
    from blueprints.settings import bp as settings_bp
    app.register_blueprint(planner_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(settings_bp)

    @app.get("/status")
    def status():
        info = {"app": "climbing-trainer", "stage": 2, "status": "ok"}
        try:
            from seed.io import get_active_plan
            active = get_active_plan()
            info["plans"] = Plan.query.count()
            info["active_plan"] = active.key if active else None
            info["phases"] = Phase.query.count()
            info["weeks"] = Week.query.count()
            info["sessions"] = Session.query.count()
            info["exercises"] = Exercise.query.count()
        except Exception:
            info["db"] = "not seeded yet — run `python -m seed.seed`"
        return jsonify(info)

    @app.get("/healthz")
    def healthz():
        return "ok", 200

    @app.context_processor
    def inject_asset_version():
        """Stamp CSS/JS links with the file's mtime so browsers fetch fresh
        styles after every deploy instead of serving a stale cached copy."""
        import os

        def asset_v(filename):
            try:
                return int(os.path.getmtime(os.path.join(app.static_folder, filename)))
            except OSError:
                return 0
        return {"asset_v": asset_v}

    return app


app = create_app()
