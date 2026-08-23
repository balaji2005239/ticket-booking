from flask import Blueprint, request, jsonify
from app.models import ROLE_CUSTOMER
from app.utils.auth import role_required, current_user
from app.services.seat_service import ERROR_SLUGS
from app.services.waitlist_service import join_waitlist, claim_offer

waitlist_bp = Blueprint("waitlist", __name__, url_prefix="/api")


def _error_response(status_code, message):
    return jsonify({"error": ERROR_SLUGS.get(status_code, "error"), "message": message}), status_code


@waitlist_bp.post("/events/<int:event_id>/waitlist")
@role_required(ROLE_CUSTOMER)
def join(event_id):
    customer = current_user()
    data = request.get_json(silent=True) or {}
    category_id = data.get("category_id")
    if not isinstance(category_id, int) or isinstance(category_id, bool):
        return jsonify({"error": "validation", "message": "category_id is required"}), 400

    entry, error = join_waitlist(event_id, category_id, customer.id)
    if error:
        return _error_response(*error)
    return jsonify({"waitlist_entry": entry.to_dict()}), 201


@waitlist_bp.post("/waitlist/claim")
@role_required(ROLE_CUSTOMER)
def claim():
    customer = current_user()
    data = request.get_json(silent=True) or {}
    offer_token = (data.get("offer_token") or "").strip()
    if not offer_token:
        return jsonify({"error": "validation", "message": "offer_token is required"}), 400

    booking, error, created = claim_offer(offer_token, customer.id)
    if error:
        return _error_response(*error)
    return jsonify({"booking": booking.to_dict()}), 201 if created else 200
