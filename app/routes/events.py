from flask import Blueprint, request, jsonify
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import (
    ROLE_ORGANISER, User, Venue,
    Event, EventPricing, EVENT_MOVIE, EVENT_CONCERT,
    Seat, SeatCategory, SeatStatus, SEAT_AVAILABLE,
    Booking, BookingSeat, BOOKING_CONFIRMED, BOOKING_CANCELLED,
)
from app.utils.auth import role_required, current_user
from app.utils.dates import parse_iso_datetime

events_bp = Blueprint("events", __name__, url_prefix="/api/organiser")

EVENT_TYPES = (EVENT_MOVIE, EVENT_CONCERT)


def _owned_event_or_404(event_id, organiser_id):
    """Fetch an event by id, scoped to the requesting organiser. None if missing/not owned."""
    return Event.query.filter_by(id=event_id, organiser_id=organiser_id).first()


def _valid_price(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _parse_pricing_entries(entries, venue_category_ids):
    """[{"category_id":..,"price":..}, ...] -> ([(category_id, price), ...], None) or (None, error_message)."""
    if not isinstance(entries, list) or not entries:
        return None, "pricing must be a non-empty list"
    parsed = []
    seen = set()
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            return None, f"pricing[{i}] must be an object"
        category_id = e.get("category_id")
        price = e.get("price")
        if category_id not in venue_category_ids:
            return None, f"pricing[{i}] category_id {category_id} does not belong to this venue"
        if not _valid_price(price):
            return None, f"pricing[{i}] price must be a positive number"
        if category_id in seen:
            return None, f"pricing[{i}] duplicate category_id {category_id}"
        seen.add(category_id)
        parsed.append((category_id, price))
    return parsed, None


# -------------------------------------------------------- venue browsing ---
# Organisers don't own venues (admins do) — these are read-only so an
# organiser can pick a venue and see its categories when creating an event.

@events_bp.get("/venues")
@role_required(ROLE_ORGANISER)
def browse_venues():
    venues = Venue.query.order_by(Venue.name).all()
    return jsonify({"venues": [v.to_dict() for v in venues]}), 200


@events_bp.get("/venues/<int:venue_id>")
@role_required(ROLE_ORGANISER)
def browse_venue_detail(venue_id):
    venue = Venue.query.get(venue_id)
    if not venue:
        return jsonify({"error": "not_found"}), 404

    data = venue.to_dict()
    data["categories"] = [c.to_dict() for c in venue.categories]
    return jsonify({"venue": data}), 200


# -------------------------------------------------------------- events ---

@events_bp.post("/events")
@role_required(ROLE_ORGANISER)
def create_event():
    organiser = current_user()
    data = request.get_json(silent=True) or {}

    title = (data.get("title") or "").strip()
    event_type = (data.get("event_type") or EVENT_MOVIE).strip().lower()
    description = (data.get("description") or "").strip() or None
    venue_id = data.get("venue_id")
    starts_at = parse_iso_datetime(data.get("starts_at"))

    if not title:
        return jsonify({"error": "validation", "message": "title is required"}), 400
    if event_type not in EVENT_TYPES:
        return jsonify({"error": "validation", "message": f"event_type must be one of {EVENT_TYPES}"}), 400
    if starts_at is None:
        return jsonify({"error": "validation", "message": "starts_at must be an ISO 8601 datetime"}), 400

    venue = Venue.query.get(venue_id)
    if not venue:
        return jsonify({"error": "validation", "message": "venue_id does not exist"}), 400

    pricing_entries = []
    if "pricing" in data:
        venue_category_ids = {c.id for c in venue.categories}
        pricing_entries, err = _parse_pricing_entries(data["pricing"], venue_category_ids)
        if err:
            return jsonify({"error": "validation", "message": err}), 400

    event = Event(
        organiser_id=organiser.id,
        venue_id=venue.id,
        title=title,
        event_type=event_type,
        description=description,
        starts_at=starts_at,
    )
    db.session.add(event)
    db.session.flush()  # assigns event.id for the rows below

    for category_id, price in pricing_entries:
        db.session.add(EventPricing(event_id=event.id, category_id=category_id, price=price))

    # Seed one seat_status row per venue seat, all 'available'. This is what the
    # seat map reads from and what the hold/checkout transactions will lock with
    # SELECT ... FOR UPDATE — rows must pre-exist for that locking to work.
    for seat in venue.seats:
        db.session.add(SeatStatus(event_id=event.id, seat_id=seat.id, status=SEAT_AVAILABLE))

    db.session.commit()
    return jsonify({"event": event.to_dict(include_pricing=True)}), 201


@events_bp.get("/events")
@role_required(ROLE_ORGANISER)
def list_events():
    organiser = current_user()
    events = (
        Event.query.filter_by(organiser_id=organiser.id)
        .order_by(Event.starts_at.desc())
        .all()
    )
    return jsonify({"events": [e.to_dict() for e in events]}), 200


@events_bp.get("/events/<int:event_id>")
@role_required(ROLE_ORGANISER)
def get_event(event_id):
    organiser = current_user()
    event = _owned_event_or_404(event_id, organiser.id)
    if not event:
        return jsonify({"error": "not_found"}), 404

    return jsonify({"event": event.to_dict(include_pricing=True)}), 200


@events_bp.patch("/events/<int:event_id>")
@role_required(ROLE_ORGANISER)
def update_event(event_id):
    organiser = current_user()
    event = _owned_event_or_404(event_id, organiser.id)
    if not event:
        return jsonify({"error": "not_found"}), 404

    data = request.get_json(silent=True) or {}
    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "validation", "message": "title cannot be empty"}), 400
        event.title = title
    if "description" in data:
        event.description = (data.get("description") or "").strip() or None
    if "event_type" in data:
        event_type = (data.get("event_type") or "").strip().lower()
        if event_type not in EVENT_TYPES:
            return jsonify({"error": "validation", "message": f"event_type must be one of {EVENT_TYPES}"}), 400
        event.event_type = event_type
    if "starts_at" in data:
        starts_at = parse_iso_datetime(data.get("starts_at"))
        if starts_at is None:
            return jsonify({"error": "validation", "message": "starts_at must be an ISO 8601 datetime"}), 400
        event.starts_at = starts_at
    # venue_id is intentionally not editable here — the seat map (built in the
    # next phase) is keyed off (event, venue) and switching venues mid-flight
    # would orphan any holds/bookings already made against it.

    db.session.commit()
    return jsonify({"event": event.to_dict(include_pricing=True)}), 200


@events_bp.delete("/events/<int:event_id>")
@role_required(ROLE_ORGANISER)
def delete_event(event_id):
    organiser = current_user()
    event = _owned_event_or_404(event_id, organiser.id)
    if not event:
        return jsonify({"error": "not_found"}), 404

    db.session.delete(event)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "error": "conflict",
            "message": "event cannot be deleted while bookings reference it",
        }), 409

    return jsonify({"message": "event deleted"}), 200


# ------------------------------------------------------------- pricing ---

@events_bp.put("/events/<int:event_id>/pricing")
@role_required(ROLE_ORGANISER)
def upsert_pricing(event_id):
    organiser = current_user()
    event = _owned_event_or_404(event_id, organiser.id)
    if not event:
        return jsonify({"error": "not_found"}), 404

    data = request.get_json(silent=True) or {}
    category_id = data.get("category_id")
    price = data.get("price")

    venue_category_ids = {c.id for c in event.venue.categories}
    if category_id not in venue_category_ids:
        return jsonify({
            "error": "validation",
            "message": "category_id does not belong to this event's venue",
        }), 400
    if not _valid_price(price):
        return jsonify({"error": "validation", "message": "price must be a positive number"}), 400

    pricing = EventPricing.query.filter_by(event_id=event.id, category_id=category_id).first()
    if pricing:
        pricing.price = price
    else:
        pricing = EventPricing(event_id=event.id, category_id=category_id, price=price)
        db.session.add(pricing)

    db.session.commit()
    return jsonify({"pricing": pricing.to_dict()}), 200


@events_bp.delete("/events/<int:event_id>/pricing/<int:category_id>")
@role_required(ROLE_ORGANISER)
def delete_pricing(event_id, category_id):
    organiser = current_user()
    event = _owned_event_or_404(event_id, organiser.id)
    if not event:
        return jsonify({"error": "not_found"}), 404

    pricing = EventPricing.query.filter_by(event_id=event.id, category_id=category_id).first()
    if not pricing:
        return jsonify({"error": "not_found"}), 404

    db.session.delete(pricing)
    db.session.commit()
    return jsonify({"message": "pricing removed"}), 200


# ------------------------------------------------- summary & bookings ---

@events_bp.get("/events/<int:event_id>/summary")
@role_required(ROLE_ORGANISER)
def event_summary(event_id):
    organiser = current_user()
    event = _owned_event_or_404(event_id, organiser.id)
    if not event:
        return jsonify({"error": "not_found"}), 404

    confirmed_count = Booking.query.filter_by(event_id=event.id, status=BOOKING_CONFIRMED).count()
    cancelled_count = Booking.query.filter_by(event_id=event.id, status=BOOKING_CANCELLED).count()

    revenue = (
        db.session.query(func.coalesce(func.sum(Booking.total), 0))
        .filter(Booking.event_id == event.id, Booking.status == BOOKING_CONFIRMED)
        .scalar()
    )

    seats_booked = (
        db.session.query(func.count(BookingSeat.id))
        .join(Booking, BookingSeat.booking_id == Booking.id)
        .filter(Booking.event_id == event.id, Booking.status == BOOKING_CONFIRMED)
        .scalar()
    )

    category_rows = (
        db.session.query(Seat.category_id, SeatCategory.name, func.count(BookingSeat.id))
        .join(BookingSeat, BookingSeat.seat_id == Seat.id)
        .join(Booking, BookingSeat.booking_id == Booking.id)
        .join(SeatCategory, SeatCategory.id == Seat.category_id)
        .filter(Booking.event_id == event.id, Booking.status == BOOKING_CONFIRMED)
        .group_by(Seat.category_id, SeatCategory.name)
        .all()
    )
    price_by_category = {p.category_id: float(p.price) for p in event.pricing}
    revenue_by_category = [
        {
            "category_id": cat_id,
            "category_name": name,
            "seats_sold": count,
            "price": price_by_category.get(cat_id),
            "revenue": round(count * price_by_category.get(cat_id, 0), 2),
        }
        for cat_id, name, count in category_rows
    ]

    return jsonify({
        "event_id": event.id,
        "confirmed_bookings": confirmed_count,
        "cancelled_bookings": cancelled_count,
        "seats_booked": seats_booked or 0,
        "revenue": float(revenue or 0),
        "revenue_by_category": revenue_by_category,
    }), 200


@events_bp.get("/events/<int:event_id>/bookings")
@role_required(ROLE_ORGANISER)
def event_bookings(event_id):
    organiser = current_user()
    event = _owned_event_or_404(event_id, organiser.id)
    if not event:
        return jsonify({"error": "not_found"}), 404

    bookings = (
        Booking.query.filter_by(event_id=event.id)
        .order_by(Booking.created_at.desc())
        .all()
    )
    customer_ids = {b.customer_id for b in bookings}
    customers = {u.id: u for u in User.query.filter(User.id.in_(customer_ids)).all()} if customer_ids else {}

    data = []
    for b in bookings:
        row = b.to_dict(include_seats=True)
        customer = customers.get(b.customer_id)
        row["customer"] = {"id": customer.id, "name": customer.name, "email": customer.email} if customer else None
        data.append(row)

    return jsonify({"bookings": data}), 200
