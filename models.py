from datetime import datetime
import secrets

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Daily study streak — maintained by app.py's record_daily_activity()
    # whenever the user opens the dashboard, saves notes, or finishes a quiz.
    # Consecutive UTC days bump current_streak; any gap (or first-ever
    # activity) resets it back to 1.
    # Both columns are nullable on purpose: an already-created `users` table
    # will not get new columns from db.create_all(), so pre-existing rows
    # start as NULL here until their next activity. New sign-ups always get
    # current_streak=0 via the column default.
    last_active_date = db.Column(db.Date, nullable=True)
    current_streak = db.Column(db.Integer, nullable=True, default=0)

    def set_password(self, raw_password):
        # werkzeug's default (pbkdf2:sha256) is fine for this scale.
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    def __repr__(self):
        return f"<User {self.email}>"


class Note(db.Model):
    """A study-notes generation saved to a user's account (👤 Dashboard ->
    Recent Notes). Separate from the browser-local history in index.html —
    this one is cloud-saved and only exists for logged-in users who tap
    "☁️ Save to My Account" after generating notes.

    Sharing:
    - is_public: when True, the note is publicly viewable via /shared-notes/<share_token>
    - share_token: generated once when the note is first made public (secrets.token_urlsafe(24)),
      stays None for private notes. If a note is toggled back to private, the old token stops
      working because the public route requires BOTH share_token match AND is_public==True.
    
    IMPORTANT: Existing SQLite databases need either:
      - ALTER TABLE notes ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT 0;
        ALTER TABLE notes ADD COLUMN share_token VARCHAR(64) UNIQUE;
        CREATE INDEX ix_notes_share_token ON notes(share_token);
      - Or a fresh db.create_all() on a new database file.
    create_all() will NOT add columns to an existing table.
    """

    __tablename__ = "notes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    topic = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255))
    class_name = db.Column(db.String(255))
    language = db.Column(db.String(64))
    content = db.Column(db.Text, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Sharing columns
    is_public = db.Column(db.Boolean, nullable=False, default=False)
    share_token = db.Column(db.String(64), unique=True, nullable=True, index=True)

    user = db.relationship("User", backref=db.backref("notes", lazy="dynamic"))

    def __repr__(self):
        return f"<Note {self.id} topic={self.topic!r} public={self.is_public}>"

    def ensure_share_token(self):
        """Generate a share token if this note is public but doesn't have one yet."""
        if self.is_public and not self.share_token:
            # 24 bytes -> 32 chars URL-safe, cryptographically random
            self.share_token = secrets.token_urlsafe(24)


class QuizResult(db.Model):
    """One completed quiz attempt for a logged-in user. Saved automatically
    when a quiz (generated from Notes) is finished. Powers the Dashboard's
    quiz average and weak-topic detection — this is the foundation for the
    later spaced-revision / "you're weak in Algebra" feature."""

    __tablename__ = "quiz_results"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    topic = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255))
    score = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship("User", backref=db.backref("quiz_results", lazy="dynamic"))

    @property
    def percent(self):
        return round((self.score / self.total) * 100) if self.total else 0

    def __repr__(self):
        return f"<QuizResult {self.id} topic={self.topic!r} {self.score}/{self.total}>"


class RevisionSchedule(db.Model):
    """Per-(user, topic) spaced-revision schedule, one row per topic a user
    has quizzed on. Driven entirely by quiz results: a strong score (>=75%)
    pushes the topic to a longer interval before its next review; a middling
    score (50-74%) repeats the same interval; a weak score (<50%) resets to
    the shortest interval. Powers the Dashboard's "📅 Revision Due" list —
    this is the roadmap's spaced-revision / "review Algebra today" feature."""

    __tablename__ = "revision_schedules"
    __table_args__ = (
        db.UniqueConstraint("user_id", "topic", name="uq_revision_user_topic"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    topic = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255))

    interval_stage = db.Column(db.Integer, nullable=False, default=0)
    last_score_pct = db.Column(db.Integer)
    last_reviewed_at = db.Column(db.DateTime, default=datetime.utcnow)
    next_review_at = db.Column(db.DateTime, nullable=False, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("revision_schedules", lazy="dynamic"))

    def __repr__(self):
        return f"<RevisionSchedule {self.id} topic={self.topic!r} stage={self.interval_stage}>"