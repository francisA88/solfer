"""
models.py — Solfer database models (Flask-SQLAlchemy)

Tables
------
  users    — registered users (email/password or Google OAuth)
  measures — solfa notation measures owned by a user
"""

from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class User(db.Model):
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)

    # Identity
    name          = db.Column(db.String(120), nullable=False)
    email         = db.Column(db.String(254), unique=True, nullable=False, index=True)

    # Auth — nullable because Google-OAuth users have no password
    password_hash = db.Column(db.String(256), nullable=True)

    # Google OAuth — nullable for email/password users
    google_id     = db.Column(db.String(128), unique=True, nullable=True, index=True)

    # Payment
    is_paid_user  = db.Column(db.Boolean, default=False, nullable=False)
    amount_paid   = db.Column(db.Numeric(10, 2), nullable=True)   # e.g. 4.99
    date_paid     = db.Column(db.DateTime(timezone=True), nullable=True)

    # Subscription validity — set when payment is confirmed via webhook
    access_until  = db.Column(db.DateTime(timezone=True), nullable=True)

    # Stripe customer/session ids (or whichever payment provider you use)
    payment_customer_id = db.Column(db.String(128), nullable=True)
    payment_ref         = db.Column(db.String(128), nullable=True)  # last charge / session id

    # Timestamps
    created_at    = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at    = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    measures      = db.relationship(
        "Measure",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="Measure.position",
        lazy="select",
    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def has_active_access(self):
        """True if the user currently has paid access."""
        if not self.is_paid_user:
            return False
        if self.access_until is None:
            return True  # lifetime / no expiry set
        # return datetime.now(timezone.utc) < self.access_until
        access_until = self.access_until
        if access_until.tzinfo is None:
            # DB returned a naive datetime — assume it's UTC (since that's what we stored)
            access_until = access_until.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < access_until

    def set_password(self, plain: str):
        """Hash and store a plaintext password."""
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(plain)

    def check_password(self, plain: str) -> bool:
        """Verify a plaintext password against the stored hash."""
        if not self.password_hash:
            return False
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, plain)

    def to_dict(self):
        return {
            "id":            self.id,
            "name":          self.name,
            "email":         self.email,
            "is_paid_user":  self.is_paid_user,
            "has_access":    self.has_active_access,
            "access_until":  self.access_until.isoformat() if self.access_until else None,
            "created_at":    self.created_at.isoformat(),
        }

    def __repr__(self):
        return f"<User id={self.id} email={self.email!r}>"


# ---------------------------------------------------------------------------
# Measure
# ---------------------------------------------------------------------------

class Measure(db.Model):
    __tablename__ = "measures"

    id             = db.Column(db.Integer, primary_key=True)
    m_id          = db.Column(db.Integer, nullable=False)  # UUID for frontend reference

    # Owner
    user_id        = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The raw solfa string for this measure,
    # e.g. "d.m:s.l:t:d'" — exactly as produced by the editor
    measure_string = db.Column(db.Text, nullable=False)

    # Human-readable label / title (optional)
    label          = db.Column(db.String(120), nullable=True)

    # Ordering within the user's composition
    position       = db.Column(db.Integer, nullable=False, default=0)

    # Metadata stored alongside the raw string so the editor can restore
    # context without re-parsing (key, time signature, part)
    key            = db.Column(db.String(8),  nullable=True)   # e.g. "C", "F#/Gb"
    time_sig       = db.Column(db.String(8),  nullable=True)   # e.g. "4/4", "3/4"
    part           = db.Column(db.String(2),  nullable=True)   # "S" | "A" | "T" | "B"

    created_at     = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at     = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    user           = db.relationship("User", back_populates="measures")

    def to_dict(self):
        return {
            "id":             self.id,
            "measure_string": self.measure_string,
            "label":          self.label,
            "position":       self.position,
            "key":            self.key,
            "time_sig":       self.time_sig,
            "part":           self.part,
            "created_at":     self.created_at.isoformat(),
            "updated_at":     self.updated_at.isoformat(),
            "m_id":           self.m_id,
        }

    def __repr__(self):
        return f"<Measure id={self.id} user_id={self.user_id} pos={self.position}>"


class Transaction(db.Model):
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(15), nullable=False, default=False)
    amount = db.Column(db.Float, nullable=False)
    tx_id = db.Column(db.String, nullable=False)
    tx_ref = db.Column(db.String, nullable=False)
    flw_ref = db.Column(db.String, nullable=False)
    cust_email = db.Column(db.String, nullable=False)

    def to_dict(self):
        return {
            "status": self.status,
            "amount": self.amount,
            "tx_id": self.tx_id,
            "tx_ref": self.tx_ref,
            "flw_ref": self.flw_ref,
            "cust_email": self.cust_email
        }

    def __repr__(self):
        return f"<Transaction tx_id={self.tx_id} amount={self.amount} status={self.status}>"