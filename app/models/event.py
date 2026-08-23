from datetime import datetime, timezone
from app.extensions import db

EVENT_MOVIE = "movie"
EVENT_CONCERT = "concert"


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    organiser_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    venue_id = db.Column(db.Integer, db.ForeignKey("venues.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    event_type = db.Column(db.String(20), nullable=False, default=EVENT_MOVIE)
    description = db.Column(db.Text)
    starts_at = db.Column(db.DateTime, nullable=False)  # date + time of the show
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    venue = db.relationship("Venue")
    pricing = db.relationship("EventPricing", backref="event", cascade="all, delete-orphan")
    # Live per-seat state for this show — ephemeral, so it cleans up with the event.
    # Booking has no such cascade: a real booking record is what should block a delete.
    seat_statuses = db.relationship("SeatStatus", cascade="all, delete-orphan")

    def to_dict(self, include_pricing=False):
        data = {
            "id": self.id,
            "organiser_id": self.organiser_id,
            "venue_id": self.venue_id,
            "venue_name": self.venue.name if self.venue else None,
            "title": self.title,
            "event_type": self.event_type,
            "description": self.description,
            "starts_at": self.starts_at.isoformat() if self.starts_at else None,
        }
        if include_pricing:
            data["pricing"] = [p.to_dict() for p in self.pricing]
        return data


class EventPricing(db.Model):
    __tablename__ = "event_pricing"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("seat_categories.id"), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)

    category = db.relationship("SeatCategory")

    __table_args__ = (
        db.UniqueConstraint("event_id", "category_id", name="uq_event_category_price"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "event_id": self.event_id,
            "category_id": self.category_id,
            "category_name": self.category.name if self.category else None,
            "price": float(self.price),
        }
