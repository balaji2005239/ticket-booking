"""
Public customer-facing browse + seat-map routes. No auth required — anyone
(including a not-yet-logged-in visitor) can browse events and look at a seat
map before signing in. Seat *holding*/booking (next phase, in
app/services/seat_service.py) is what requires a customer JWT.
"""
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify
from sqlalchemy import func
from app.extensions import db
from app.models import (
    Event, EventPricing, EVENT_MOVIE, EVENT_CONCERT,
    Seat, SeatStatus, SEAT_AVAILABLE,
)
from app.utils.dates import parse_iso_datetime, parse_date

browse_bp = Blueprint("browse", __name__, url_prefix="/api/events")

EVENT_TYPES = (EVENT_MOVIE, EVENT_CONCERT)


@browse_bp.get("")
def list_events():
    event_type = (request.args.get("event_type") or "").strip().lower() or None
    venue_id = request.args.get("venue_id", type=int)
    q = (request.args.get("q") or "").strip()
    date_str = request.args.get("date")
    from_str = request.args.get("from")
    to_str = request.args.get("to")
    upcoming_only = (request.args.get("upcoming_only", "true").strip().lower() != "false")

    page = max(request.args.get("page", 1, type=int) or 1, 1)
    per_page = min(max(request.args.get("per_page", 20, type=int) or 20, 1), 100)

    if event_type and event_type not in EVENT_TYPES:
        return jsonify({"error": "validation", "message": f"event_type must be one of {EVENT_TYPES}"}), 400

    query = Event.query
    if event_type:
        query = query.filter(Event.event_type == event_type)
    if venue_id:
        query = query.filter(Event.venue_id == venue_id)
    if q:
        query = query.filter(Event.title.ilike(f"%{q}%"))

    if date_str:
        day = parse_date(date_str)
        if day is None:
            return jsonify({"error": "validation", "message": "date must be YYYY-MM-DD"}), 400
        start = datetime.combine(day, datetime.min.time())
        query = query.filter(Event.starts_at >= start, Event.starts_at < start + timedelta(days=1))
    else:
        if from_str:
            dt = parse_iso_datetime(from_str)
            if dt is None:
                return jsonify({"error": "validation", "message": "from must be an ISO 8601 datetime"}), 400
            query = query.filter(Event.starts_at >= dt)
        if to_str:
            dt = parse_iso_datetime(to_str)
            if dt is None:
                return jsonify({"error": "validation", "message": "to must be an ISO 8601 datetime"}), 400
            query = query.filter(Event.starts_at <= dt)
        elif upcoming_only:
            query = query.filter(Event.starts_at >= datetime.now(timezone.utc).replace(tzinfo=None))

    total = query.count()
    events = (
        query.order_by(Event.starts_at.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    price_from = {}
    if events:
        price_from = dict(
            db.session.query(EventPricing.event_id, func.min(EventPricing.price))
            .filter(EventPricing.event_id.in_([e.id for e in events]))
            .group_by(EventPricing.event_id)
            .all()
        )

    data = []
    for e in events:
        row = e.to_dict()
        price = price_from.get(e.id)
        row["price_from"] = float(price) if price is not None else None
        data.append(row)

    return jsonify({"events": data, "page": page, "per_page": per_page, "total": total}), 200


@browse_bp.get("/<int:event_id>")
def get_event_detail(event_id):
    event = Event.query.get(event_id)
    if not event:
        return jsonify({"error": "not_found"}), 404

    data = event.to_dict(include_pricing=True)
    data["venue"] = event.venue.to_dict() if event.venue else None

    price_by_category = {p.category_id: float(p.price) for p in event.pricing}

    available_counts = dict(
        db.session.query(Seat.category_id, func.count(SeatStatus.id))
        .join(SeatStatus, (SeatStatus.seat_id == Seat.id) & (SeatStatus.event_id == event.id))
        .filter(SeatStatus.status == SEAT_AVAILABLE)
        .group_by(Seat.category_id)
        .all()
    )
    total_counts = dict(
        db.session.query(Seat.category_id, func.count(Seat.id))
        .filter(Seat.venue_id == event.venue_id)
        .group_by(Seat.category_id)
        .all()
    )

    availability = [
        {
            "category_id": cat.id,
            "category_name": cat.name,
            "price": price_by_category.get(cat.id),
            "total_seats": total_counts.get(cat.id, 0),
            "available_seats": available_counts.get(cat.id, 0),
        }
        for cat in (event.venue.categories if event.venue else [])
    ]
    data["availability"] = availability
    data["sold_out"] = bool(availability) and all(a["available_seats"] == 0 for a in availability)

    return jsonify({"event": data}), 200


@browse_bp.get("/<int:event_id>/seatmap")
def get_seatmap(event_id):
    event = Event.query.get(event_id)
    if not event:
        return jsonify({"error": "not_found"}), 404

    price_by_category = {p.category_id: float(p.price) for p in event.pricing}

    # LEFT JOIN so a seat missing a seat_status row (shouldn't normally happen —
    # rows are seeded on event create / bulk seat add) still renders as available
    # instead of vanishing from the map.
    rows = (
        db.session.query(Seat, SeatStatus.status)
        .outerjoin(SeatStatus, (SeatStatus.seat_id == Seat.id) & (SeatStatus.event_id == event.id))
        .filter(Seat.venue_id == event.venue_id)
        .order_by(Seat.row_label.asc(), Seat.seat_number.asc())
        .all()
    )

    by_row = {}
    for seat, status in rows:
        by_row.setdefault(seat.row_label, []).append({
            "seat_id": seat.id,
            "row_label": seat.row_label,
            "seat_number": seat.seat_number,
            "label": f"{seat.row_label}{seat.seat_number}",
            "category_id": seat.category_id,
            "price": price_by_category.get(seat.category_id),
            "status": status or SEAT_AVAILABLE,
        })

    seat_rows = [{"row_label": rl, "seats": seats} for rl, seats in sorted(by_row.items())]
    categories = [
        {"id": c.id, "name": c.name, "price": price_by_category.get(c.id)}
        for c in (event.venue.categories if event.venue else [])
    ]

    return jsonify({"event_id": event.id, "categories": categories, "rows": seat_rows}), 200
