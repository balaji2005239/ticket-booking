import uuid
from datetime import datetime, timezone
from app.extensions import db

BOOKING_CONFIRMED = "confirmed"
BOOKING_CANCELLED = "cancelled"


def _gen_ref():
    return uuid.uuid4().hex[:12].upper()


class Booking(db.Model):
    __tablename__ = "bookings"

    id = db.Column(db.Integer, primary_key=True)
    ref = db.Column(db.String(16), unique=True, nullable=False, default=_gen_ref, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    total = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    status = db.Column(db.String(12), nullable=False, default=BOOKING_CONFIRMED)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    cancelled_at = db.Column(db.DateTime)
    # The seat_status.hold_key consumed to create this booking. Lets checkout() be
    # idempotent: a retried request with the same hold_key finds this row instead
    # of erroring or double-booking. Not exposed in to_dict() — internal only.
    hold_key = db.Column(db.String(64), unique=True, index=True)

    event = db.relationship("Event")
    seats = db.relationship("BookingSeat", backref="booking", cascade="all, delete-orphan")

    def to_dict(self, include_seats=True):
        data = {
            "id": self.id,
            "ref": self.ref,
            "event_id": self.event_id,
            "event_title": self.event.title if self.event else None,
            "starts_at": self.event.starts_at.isoformat() if self.event and self.event.starts_at else None,
            "total": float(self.total),
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_seats:
            data["seats"] = [bs.label for bs in self.seats]
        return data


class BookingSeat(db.Model):
    __tablename__ = "booking_seats"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False)
    seat_id = db.Column(db.Integer, db.ForeignKey("seats.id"), nullable=False)
    label = db.Column(db.String(16))  # snapshot e.g. "A12" for the ticket

    seat = db.relationship("Seat")
