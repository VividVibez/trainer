"""
Export the live exercise pool and each plan to portable JSON.

    python -m seed.export                # -> ./exports/
    python -m seed.export /target/dir

The files round-trip with the importer (Settings upload, or `seed.io.load_*`):
they are the exact artifact to edit and re-import for a plan change.
"""
import json
import os
import sys

from app import create_app
from models import Plan
from seed.io import export_exercises, export_plan


def run(outdir):
    os.makedirs(outdir, exist_ok=True)
    app = create_app()
    with app.app_context():
        def write(name, doc):
            path = os.path.join(outdir, name)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=2)
            print(f"  wrote {path}  ({os.path.getsize(path):,} bytes)")

        write("exercises.json", export_exercises())
        for plan in Plan.query.order_by(Plan.order_index):
            write(f"{plan.key}.json", export_plan(plan))


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "exports")
