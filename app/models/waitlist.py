import uuid
from datetime import datetime, timezone
from app.extensions import db

# Waitlist entry lifecycle
WL_WAITING = "waiting"      # in the FIFO queue
WL_OFFERED = "offered"      # a freed seat is being offered to this entry (time-limited)
WL_CONVERTED = "converted"  # entry claimed the offer and booked
WL_EXPIRED = "expired"      # offer window lapsed; passed on to next in line
WL_CANCELLED = "cancelled"  # customer left the waitlist


def _gen_token():
    return uuid.uuid4().hex


class Waitlist(db.Model):
    """
    FIFO queue per (event, seat_category). On a cancellation the next waiting
    entry is moved to 'offered' with a time-limited claim token and offer_expires_at.
    The scheduler expires stale offers and cascades to the next entry.
    """
    __tablename__ = "waitlist"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("seat_categories.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    status = db.Column(db.String(12), nullable=False, default=WL_WAITING, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    # Offer bookkeeping — populated only while status == offered
    offer_token = db.Column(db.String(64), index=True)
    offer_seat_id = db.Column(db.Integer, db.ForeignKey("seats.id"))
    offer_expires_at = db.Column(db.DateTime)

    category = db.relationship("SeatCategory")

    def to_dict(self):
        return {
            "id": self.id,
            "event_id": self.event_id,
            "category_id": self.category_id,
            "category_name": self.category.name if self.category else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "offer_expires_at": self.offer_expires_at.isoformat() if self.offer_expires_at else None,
        }
