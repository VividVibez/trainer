"""
Database schema for the climbing training planner.

Design notes
------------
* MULTI-PLAN. A Plan is a self-contained training plan (its own phases,
  sessions, weeks, counts, deloads). Plans are created/overwritten by importing
  a JSON file; an arbitrary number can coexist. The *active* plan is stored in
  Setting('active_plan_key'). Phases, sessions and weeks all carry plan_id.
* Exercises are a SHARED global pool (not plan-scoped) keyed by unique name, so
  two plans can reference the same "Max Hangs – Strength" entry. New exercises
  are appended via their own import file (duplicates rejected by name).
* Planning-only, no workout logging (Hevy owns that) and no versioning — edits
  apply globally/immediately. The only per-week user state is DayAssignment,
  which scopes to a plan via its Week (each plan keeps its own day placements).
* The 3/4 toggle is data-driven per plan: each Session carries count_four /
  count_three; the Plan carries the parity rule and which toggle values are
  allowed. The per-plan Push session is phase_id = NULL (plan-global).
"""
from extensions import db


exercise_tags = db.Table(
    "exercise_tags",
    db.Column("exercise_id", db.Integer,
              db.ForeignKey("exercise.id", ondelete="CASCADE"), primary_key=True),
    db.Column("tag_id", db.Integer,
              db.ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True),
)


class Plan(db.Model):
    """One self-contained training plan. Imported from / exported to JSON."""
    __tablename__ = "plan"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(60), unique=True, nullable=False)   # stable id from the file
    name = db.Column(db.String(120), nullable=False)
    weeks = db.Column(db.Integer, nullable=False)
    count_mode = db.Column(db.String(20), default="parity")       # how weekly counts are derived
    count_odd = db.Column(db.Integer, default=4)                  # parity: centre count on odd weeks
    count_even = db.Column(db.Integer, default=3)                 # parity: centre count on even weeks
    toggle_options = db.Column(db.String(40), default="3,4")      # csv of allowed toggle values
    order_index = db.Column(db.Integer, default=0)               # display order in Settings

    phases = db.relationship("Phase", backref="plan", order_by="Phase.order_index",
                             cascade="all, delete-orphan")
    sessions = db.relationship("Session", backref="plan", cascade="all, delete-orphan")
    weeks_rel = db.relationship("Week", backref="plan", order_by="Week.week_number",
                                cascade="all, delete-orphan")

    @property
    def toggle_values(self):
        return [int(x) for x in self.toggle_options.split(",") if x.strip()]

    def __repr__(self):
        return f"<Plan {self.key} '{self.name}' ({self.weeks}w)>"


class Phase(db.Model):
    """One block within a plan."""
    __tablename__ = "phase"
    __table_args__ = (db.UniqueConstraint("plan_id", "slug", name="uq_phase_plan_slug"),)

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("plan.id"), nullable=False)
    slug = db.Column(db.String(40), nullable=False)          # unique within a plan, not globally
    name = db.Column(db.String(80), nullable=False)
    header_label = db.Column(db.String(40), nullable=False)
    subtitle = db.Column(db.String(140))
    week_start = db.Column(db.Integer, nullable=False)
    week_end = db.Column(db.Integer, nullable=False)
    order_index = db.Column(db.Integer, nullable=False)
    color = db.Column(db.String(9), nullable=False)
    goal = db.Column(db.Text)
    overview = db.Column(db.Text)
    deload_note = db.Column(db.Text)

    weeks = db.relationship("Week", backref="phase", order_by="Week.week_number")
    sessions = db.relationship(
        "Session", backref="phase", order_by="Session.order_index",
        primaryjoin="Phase.id == Session.phase_id",
    )

    def __repr__(self):
        return f"<Phase {self.order_index}:{self.slug} W{self.week_start}-{self.week_end}>"


class Week(db.Model):
    """A single week within a plan. Surrogate id PK so DayAssignment scopes per
    plan via week_id; (plan_id, week_number) is the natural key."""
    __tablename__ = "week"
    __table_args__ = (db.UniqueConstraint("plan_id", "week_number", name="uq_week_plan_num"),)

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("plan.id"), nullable=False)
    week_number = db.Column(db.Integer, nullable=False)         # 1..plan.weeks
    phase_id = db.Column(db.Integer, db.ForeignKey("phase.id"), nullable=False)
    is_deload = db.Column(db.Boolean, default=False, nullable=False)
    expected_sessions = db.Column(db.Integer, nullable=False)   # parity default (centre count)
    planned_sessions = db.Column(db.Integer)                    # toggle override; NULL = use expected

    assignments = db.relationship(
        "DayAssignment", backref="week", order_by="DayAssignment.position",
        cascade="all, delete-orphan",
    )

    @property
    def session_count(self):
        return self.planned_sessions or self.expected_sessions

    @property
    def position_in_phase(self):
        return self.week_number - self.phase.week_start + 1

    @property
    def phase_length(self):
        return self.phase.week_end - self.phase.week_start + 1

    def __repr__(self):
        return f"<Week p{self.plan_id} #{self.week_number}{' (deload)' if self.is_deload else ''}>"


class Session(db.Model):
    """An editable preset session within a plan. phase_id = NULL marks the
    plan-global Push/Antagonist session (appears every week of its plan)."""
    __tablename__ = "session"

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("plan.id"), nullable=False)
    phase_id = db.Column(db.Integer, db.ForeignKey("phase.id"))   # NULL = plan-global (Push)
    type_letter = db.Column(db.String(1), nullable=False)        # A / B / C / D / P
    name = db.Column(db.String(80), nullable=False)
    location = db.Column(db.String(40))
    duration = db.Column(db.String(40))
    cns_level = db.Column(db.String(40))
    session_rules = db.Column(db.Text)
    order_index = db.Column(db.Integer, default=0)
    count_four = db.Column(db.Integer, default=1)
    count_three = db.Column(db.Integer, default=1)

    exercises = db.relationship(
        "SessionExercise", backref="session", order_by="SessionExercise.position",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        scope = self.phase.slug if self.phase else "plan-global"
        return f"<Session {self.type_letter}:{self.name} ({scope})>"


class Exercise(db.Model):
    """A shared Dictionary entry (NOT plan-scoped). Unique by name; phase
    variants are separate rows (e.g. 'Max Hangs – Strength' vs '… – Base')."""
    __tablename__ = "exercise"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    variant_label = db.Column(db.String(40))
    kind = db.Column(db.String(12), default="main")
    duration = db.Column(db.String(40))    # e.g. "15 min", shown in collapsed header
    detail = db.Column(db.Text)            # coaching notes / fallback paragraph
    steps = db.Column(db.Text)            # newline-delimited steps; renders as numbered list

    tags = db.relationship("Tag", secondary=exercise_tags, backref="exercises")
    links = db.relationship("SessionExercise", backref="exercise")

    def __repr__(self):
        return f"<Exercise {self.name}>"


class SessionExercise(db.Model):
    """Ordered link between a Session and an Exercise. is_locked pins warm-ups
    and cool-downs (not reorderable in the session detail view)."""
    __tablename__ = "session_exercise"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer,
                           db.ForeignKey("session.id", ondelete="CASCADE"), nullable=False)
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercise.id"), nullable=False)
    position = db.Column(db.Integer, nullable=False)
    is_locked = db.Column(db.Boolean, default=False)


class Tag(db.Model):
    __tablename__ = "tag"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), unique=True, nullable=False)

    def __repr__(self):
        return f"<Tag {self.name}>"


class DayAssignment(db.Model):
    """User planning state: a session placed on a day of a given week, with a
    done-tick. Scopes to a plan via week_id, so each plan keeps its own board."""
    __tablename__ = "day_assignment"

    id = db.Column(db.Integer, primary_key=True)
    week_id = db.Column(db.Integer, db.ForeignKey("week.id"), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("session.id"), nullable=False)
    day_index = db.Column(db.Integer)                          # 1..7, NULL = unassigned/in tray
    is_done = db.Column(db.Boolean, default=False, nullable=False)
    position = db.Column(db.Integer, default=0)

    session = db.relationship("Session")


class Setting(db.Model):
    """Key/value store, shared across plans. Keys: plan_start_date,
    active_plan_key."""
    __tablename__ = "setting"

    key = db.Column(db.String(40), primary_key=True)
    value = db.Column(db.String(200))

    def __repr__(self):
        return f"<Setting {self.key}={self.value}>"
