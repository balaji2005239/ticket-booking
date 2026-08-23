from datetime import datetime, timezone
from app.extensions import db


class Venue(db.Model):
    __tablename__ = "venues"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(500))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    categories = db.relationship("SeatCategory", backref="venue", cascade="all, delete-orphan")
    seats = db.relationship("Seat", backref="venue", cascade="all, delete-orphan")

    def to_dict(self, include_layout=False):
        data = {
            "id": self.id,
            "name": self.name,
            "address": self.address,
        }
        if include_layout:
            data["categories"] = [c.to_dict() for c in self.categories]
            data["seats"] = [s.to_dict() for s in self.seats]
        return data


class SeatCategory(db.Model):
    __tablename__ = "seat_categories"

    id = db.Column(db.Integer, primary_key=True)
    venue_id = db.Column(db.Integer, db.ForeignKey("venues.id"), nullable=False)
    name = db.Column(db.String(80), nullable=False)  # e.g. Premium, Standard

    def to_dict(self):
        return {"id": self.id, "venue_id": self.venue_id, "name": self.name}


class Seat(db.Model):
    __tablename__ = "seats"

    id = db.Column(db.Integer, primary_key=True)
    venue_id = db.Column(db.Integer, db.ForeignKey("venues.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("seat_categories.id"), nullable=False)
    row_label = db.Column(db.String(8), nullable=False)   # e.g. "A"
    seat_number = db.Column(db.Integer, nullable=False)     # e.g. 12

    category = db.relationship("SeatCategory")

    __table_args__ = (
        db.UniqueConstraint("venue_id", "row_label", "seat_number", name="uq_seat_position"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "venue_id": self.venue_id,
            "category_id": self.category_id,
            "row_label": self.row_label,
            "seat_number": self.seat_number,
            "label": f"{self.row_label}{self.seat_number}",
        }
