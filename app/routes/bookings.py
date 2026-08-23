from flask import Blueprint, request, jsonify
from app.models import ROLE_CUSTOMER, Event, Booking
from app.utils.auth import role_required, current_user
from app.services.seat_service import hold_seats, release_hold, checkout, cancel_booking, ERROR_SLUGS

bookings_bp = Blueprint("bookings", __name__, url_prefix="/api")


def _error_response(status_code, message):
    return jsonify({"error": ERROR_SLUGS.get(status_code, "error"), "message": message}), status_code


@bookings_bp.post("/events/<int:event_id>/hold")
@role_required(ROLE_CUSTOMER)
def hold(event_id):
    customer = current_user()
    event = Event.query.get(event_id)
    if not event:
        return jsonify({"error": "not_found"}), 404

    data = request.get_json(silent=True) or {}
    seat_ids = data.get("seat_ids")
    if not isinstance(seat_ids, list) or not seat_ids or not all(
        isinstance(s, int) and not isinstance(s, bool) for s in seat_ids
    ):
        return jsonify({"error": "validation", "message": "seat_ids must be a non-empty list of integers"}), 400

    result, error = hold_seats(event_id, seat_ids, customer.id)
    if error:
        return _error_response(*error)
    return jsonify({"hold": result}), 201


@bookings_bp.delete("/holds/<hold_key>")
@role_required(ROLE_CUSTOMER)
def release(hold_key):
    customer = current_user()
    result, error = release_hold(hold_key, customer.id)
    if error:
        return _error_response(*error)
    return jsonify(result), 200


@bookings_bp.post("/checkout")
@role_required(ROLE_CUSTOMER)
def do_checkout():
    customer = current_user()
    data = request.get_json(silent=True) or {}
    hold_key = (data.get("hold_key") or "").strip()
    if not hold_key:
        return jsonify({"error": "validation", "message": "hold_key is required"}), 400

    booking, error, created = checkout(hold_key, customer.id)
    if error:
        return _error_response(*error)
    return jsonify({"booking": booking.to_dict()}), 201 if created else 200


# --------------------------------------------------------- booking history ---

@bookings_bp.get("/bookings")
@role_required(ROLE_CUSTOMER)
def list_bookings():
    customer = current_user()
    bookings = (
        Booking.query.filter_by(customer_id=customer.id)
        .order_by(Booking.created_at.desc())
        .all()
    )
    return jsonify({"bookings": [b.to_dict() for b in bookings]}), 200


@bookings_bp.get("/bookings/<int:booking_id>")
@role_required(ROLE_CUSTOMER)
def get_booking(booking_id):
    customer = current_user()
    booking = Booking.query.filter_by(id=booking_id, customer_id=customer.id).first()
    if not booking:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"booking": booking.to_dict()}), 200


@bookings_bp.delete("/bookings/<int:booking_id>")
@role_required(ROLE_CUSTOMER)
def delete_booking(booking_id):
    customer = current_user()
    booking, error = cancel_booking(booking_id, customer.id)
    if error:
        return _error_response(*error)
    return jsonify({"booking": booking.to_dict()}), 200
