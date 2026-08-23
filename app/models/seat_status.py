from app.extensions import db

# Seat status values for a given event
SEAT_AVAILABLE = "available"
SEAT_HELD = "held"
SEAT_BOOKED = "booked"


class SeatStatus(db.Model):
    """
    One row per (event, seat). This is the single source of truth for whether a
    seat is available, held (with a TTL), or booked for a specific show.

    Concurrency is enforced by selecting these rows FOR UPDATE inside the hold
    and checkout transactions, plus the unique constraint below.
    """
    __tablename__ = "seat_status"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False, index=True)
    seat_id = db.Column(db.Integer, db.ForeignKey("seats.id"), nullable=False)

    status = db.Column(db.String(12), nullable=False, default=SEAT_AVAILABLE, index=True)

    # Hold bookkeeping — populated only while status == held
    held_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    hold_key = db.Column(db.String(64), index=True)
    hold_expires_at = db.Column(db.DateTime)  # UTC

    seat = db.relationship("Seat")

    __table_args__ = (
        db.UniqueConstraint("event_id", "seat_id", name="uq_event_seat"),
    )

    def to_dict(self):
        s = self.seat
        return {
            "seat_status_id": self.id,
            "seat_id": self.seat_id,
            "event_id": self.event_id,
            "status": self.status,
            "row_label": s.row_label if s else None,
            "seat_number": s.seat_number if s else None,
            "label": f"{s.row_label}{s.seat_number}" if s else None,
            "category_id": s.category_id if s else None,
        }
