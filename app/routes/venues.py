from flask import Blueprint, request, jsonify
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import ROLE_ADMIN, Venue, SeatCategory, Seat, Event, SeatStatus, SEAT_AVAILABLE
from app.utils.auth import role_required, current_user

venues_bp = Blueprint("venues", __name__, url_prefix="/api/admin/venues")


def _owned_venue_or_404(venue_id, admin_id):
    """Fetch a venue by id, scoped to the requesting admin. None if missing/not owned."""
    return Venue.query.filter_by(id=venue_id, created_by=admin_id).first()


def _owned_category_or_404(venue, category_id):
    return next((c for c in venue.categories if c.id == category_id), None)


# ---------------------------------------------------------------- venues ---

@venues_bp.post("")
@role_required(ROLE_ADMIN)
def create_venue():
    admin = current_user()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    address = (data.get("address") or "").strip() or None

    if not name:
        return jsonify({"error": "validation", "message": "name is required"}), 400

    venue = Venue(name=name, address=address, created_by=admin.id)
    db.session.add(venue)
    db.session.commit()

    return jsonify({"venue": venue.to_dict()}), 201


@venues_bp.get("")
@role_required(ROLE_ADMIN)
def list_venues():
    admin = current_user()
    venues = (
        Venue.query.filter_by(created_by=admin.id)
        .order_by(Venue.created_at.desc())
        .all()
    )
    return jsonify({"venues": [v.to_dict() for v in venues]}), 200


@venues_bp.get("/<int:venue_id>")
@role_required(ROLE_ADMIN)
def get_venue(venue_id):
    admin = current_user()
    venue = _owned_venue_or_404(venue_id, admin.id)
    if not venue:
        return jsonify({"error": "not_found"}), 404

    return jsonify({"venue": venue.to_dict(include_layout=True)}), 200


@venues_bp.patch("/<int:venue_id>")
@role_required(ROLE_ADMIN)
def update_venue(venue_id):
    admin = current_user()
    venue = _owned_venue_or_404(venue_id, admin.id)
    if not venue:
        return jsonify({"error": "not_found"}), 404

    data = request.get_json(silent=True) or {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "validation", "message": "name cannot be empty"}), 400
        venue.name = name
    if "address" in data:
        venue.address = (data.get("address") or "").strip() or None

    db.session.commit()
    return jsonify({"venue": venue.to_dict()}), 200


@venues_bp.delete("/<int:venue_id>")
@role_required(ROLE_ADMIN)
def delete_venue(venue_id):
    admin = current_user()
    venue = _owned_venue_or_404(venue_id, admin.id)
    if not venue:
        return jsonify({"error": "not_found"}), 404

    db.session.delete(venue)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "error": "conflict",
            "message": "venue cannot be deleted while events reference it",
        }), 409

    return jsonify({"message": "venue deleted"}), 200


# ------------------------------------------------------------ categories ---

@venues_bp.post("/<int:venue_id>/categories")
@role_required(ROLE_ADMIN)
def add_category(venue_id):
    admin = current_user()
    venue = _owned_venue_or_404(venue_id, admin.id)
    if not venue:
        return jsonify({"error": "not_found"}), 404

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "validation", "message": "name is required"}), 400
    if any(c.name.lower() == name.lower() for c in venue.categories):
        return jsonify({"error": "conflict", "message": "category already exists for this venue"}), 409

    category = SeatCategory(venue_id=venue.id, name=name)
    db.session.add(category)
    db.session.commit()

    return jsonify({"category": category.to_dict()}), 201


@venues_bp.patch("/<int:venue_id>/categories/<int:category_id>")
@role_required(ROLE_ADMIN)
def update_category(venue_id, category_id):
    admin = current_user()
    venue = _owned_venue_or_404(venue_id, admin.id)
    if not venue:
        return jsonify({"error": "not_found"}), 404
    category = _owned_category_or_404(venue, category_id)
    if not category:
        return jsonify({"error": "not_found"}), 404

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "validation", "message": "name is required"}), 400
    if any(c.id != category.id and c.name.lower() == name.lower() for c in venue.categories):
        return jsonify({"error": "conflict", "message": "category already exists for this venue"}), 409

    category.name = name
    db.session.commit()
    return jsonify({"category": category.to_dict()}), 200


@venues_bp.delete("/<int:venue_id>/categories/<int:category_id>")
@role_required(ROLE_ADMIN)
def delete_category(venue_id, category_id):
    admin = current_user()
    venue = _owned_venue_or_404(venue_id, admin.id)
    if not venue:
        return jsonify({"error": "not_found"}), 404
    category = _owned_category_or_404(venue, category_id)
    if not category:
        return jsonify({"error": "not_found"}), 404

    db.session.delete(category)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "error": "conflict",
            "message": "category cannot be deleted while seats or pricing reference it",
        }), 409

    return jsonify({"message": "category deleted"}), 200


# ------------------------------------------------------------------ seats ---

@venues_bp.post("/<int:venue_id>/seats/bulk")
@role_required(ROLE_ADMIN)
def bulk_create_seats(venue_id):
    """
    Two request shapes, pick one:

    1) Generative — a block of rows sharing one category:
       {"rows": ["A", "B", "C"], "seats_per_row": 10, "category_id": 3,
        "start_seat_number": 1}   # start_seat_number optional, default 1

    2) Explicit — a full seat list, categories can vary per seat:
       {"seats": [{"row_label": "A", "seat_number": 1, "category_id": 3}, ...]}
    """
    admin = current_user()
    venue = _owned_venue_or_404(venue_id, admin.id)
    if not venue:
        return jsonify({"error": "not_found"}), 404

    data = request.get_json(silent=True) or {}
    venue_category_ids = {c.id for c in venue.categories}

    if "seats" in data:
        raw_seats = data.get("seats")
        if not isinstance(raw_seats, list) or not raw_seats:
            return jsonify({"error": "validation", "message": "seats must be a non-empty list"}), 400

        to_create = []
        for i, row in enumerate(raw_seats):
            if not isinstance(row, dict):
                return jsonify({"error": "validation", "message": f"seats[{i}] must be an object"}), 400
            row_label = str(row.get("row_label") or "").strip()
            seat_number = row.get("seat_number")
            category_id = row.get("category_id")
            if not row_label or not isinstance(seat_number, int) or seat_number < 1:
                return jsonify({
                    "error": "validation",
                    "message": f"seats[{i}] needs row_label and a positive integer seat_number",
                }), 400
            if category_id not in venue_category_ids:
                return jsonify({
                    "error": "validation",
                    "message": f"seats[{i}] category_id {category_id} does not belong to this venue",
                }), 400
            to_create.append((row_label, seat_number, category_id))

    else:
        rows = data.get("rows")
        seats_per_row = data.get("seats_per_row")
        category_id = data.get("category_id")
        start_seat_number = data.get("start_seat_number", 1)

        if not isinstance(rows, list) or not rows or not all(str(r).strip() for r in rows):
            return jsonify({"error": "validation", "message": "rows must be a non-empty list of row labels"}), 400
        if not isinstance(seats_per_row, int) or seats_per_row < 1:
            return jsonify({"error": "validation", "message": "seats_per_row must be a positive integer"}), 400
        if not isinstance(start_seat_number, int) or start_seat_number < 1:
            return jsonify({"error": "validation", "message": "start_seat_number must be a positive integer"}), 400
        if category_id not in venue_category_ids:
            return jsonify({
                "error": "validation",
                "message": f"category_id {category_id} does not belong to this venue",
            }), 400

        to_create = [
            (str(row_label).strip(), seat_number, category_id)
            for row_label in rows
            for seat_number in range(start_seat_number, start_seat_number + seats_per_row)
        ]

    # Duplicate check within the request itself
    seen = set()
    dupes_in_request = set()
    for row_label, seat_number, _ in to_create:
        key = (row_label, seat_number)
        if key in seen:
            dupes_in_request.add(key)
        seen.add(key)
    if dupes_in_request:
        return jsonify({
            "error": "validation",
            "message": "duplicate row_label/seat_number pairs in request",
            "duplicates": [f"{r}{n}" for r, n in sorted(dupes_in_request)],
        }), 400

    # Duplicate check against existing seats in the venue
    existing = {(s.row_label, s.seat_number) for s in venue.seats}
    conflicts = sorted(f"{r}{n}" for r, n, _ in to_create if (r, n) in existing)
    if conflicts:
        return jsonify({
            "error": "conflict",
            "message": "some seats already exist for this venue",
            "conflicts": conflicts,
        }), 409

    seats = [
        Seat(venue_id=venue.id, row_label=row_label, seat_number=seat_number, category_id=category_id)
        for row_label, seat_number, category_id in to_create
    ]
    db.session.add_all(seats)
    db.session.flush()  # assigns seat.id for the seat_status rows below

    # Backfill seat_status for any events already created against this venue
    # (the common path — event creation seeds these itself for seats that
    # existed at that time — is in routes/events.py).
    event_ids = [e.id for e in Event.query.filter_by(venue_id=venue.id).all()]
    for event_id in event_ids:
        for seat in seats:
            db.session.add(SeatStatus(event_id=event_id, seat_id=seat.id, status=SEAT_AVAILABLE))

    db.session.commit()

    return jsonify({
        "created": len(seats),
        "seats": [s.to_dict() for s in seats],
    }), 201
