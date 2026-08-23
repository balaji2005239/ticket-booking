"""
Core booking concurrency logic.

Two customers must never hold or book the same seat. This is enforced with:
  - a DB unique constraint on (event_id, seat_id) in seat_status (schema-level,
    see app/models/seat_status.py)
  - SELECT ... FOR UPDATE row locks inside every transaction that reads-then-writes
    a seat_status row, so concurrent requests for the same seat serialize instead
    of racing. First transaction to commit wins; the loser re-reads post-lock
    state and gets a 409/410, never a duplicate hold or booking.

Seat holds carry a TTL (config HOLD_TTL_SECONDS, default 10 min).
release_expired_holds() is the scheduler target (app/scheduler.py) that sweeps
stale holds back to 'available' every SCHEDULER_INTERVAL_SECONDS.

Every function here returns (result, error) — or (result, error, created) for
checkout(), which also reports whether it did fresh work or replayed an
idempotent hit — rather than raising, so route handlers can translate
(status_code, message) directly into a JSON error response.
"""
import uuid
from datetime import datetime, timedelta, timezone

from flask import current_app

from app.extensions import db
from app.models import (
    SeatStatus, SEAT_AVAILABLE, SEAT_HELD, SEAT_BOOKED,
    EventPricing, Booking, BookingSeat, BOOKING_CONFIRMED, BOOKING_CANCELLED,
)
from app.utils.locking import lock_for_update

# HTTP status -> short error slug, matching the {"error": ..., "message": ...} shape
# used across the other route files.
ERROR_SLUGS = {400: "validation", 403: "forbidden", 404: "not_found", 409: "conflict", 410: "expired"}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _seat_label(seat):
    return f"{seat.row_label}{seat.seat_number}" if seat else None


def hold_seats(event_id, seat_ids, customer_id, ttl_seconds=None):
    """
    Attempt to hold `seat_ids` for `event_id` on behalf of `customer_id`.
    Returns (hold_dict, None) on success or (None, (status_code, message)) on failure.
    """
    if not seat_ids:
        return None, (400, "seat_ids must be a non-empty list of integers")

    seat_ids = sorted(set(seat_ids))  # de-dup + fixed lock order (avoids deadlocks on multi-seat holds)
    ttl = ttl_seconds or current_app.config["HOLD_TTL_SECONDS"]
    now = _now()

    query = (
        SeatStatus.query
        .filter(SeatStatus.event_id == event_id, SeatStatus.seat_id.in_(seat_ids))
        .order_by(SeatStatus.seat_id.asc())
    )
    rows = lock_for_update(query).all()

    if len(rows) != len(seat_ids):
        db.session.rollback()
        missing = sorted(set(seat_ids) - {r.seat_id for r in rows})
        return None, (400, f"unknown seat_id(s) for this event: {missing}")

    unavailable = []
    for row in rows:
        if row.status == SEAT_BOOKED:
            unavailable.append(_seat_label(row.seat))
        elif row.status == SEAT_HELD and row.held_by != customer_id:
            # A live hold by someone else blocks. An expired hold (or one this
            # same customer already holds) is treated as claimable.
            if row.hold_expires_at and row.hold_expires_at > now:
                unavailable.append(_seat_label(row.seat))
    if unavailable:
        db.session.rollback()
        return None, (409, f"seats already held/booked: {', '.join(unavailable)}")

    hold_key = uuid.uuid4().hex
    expires_at = now + timedelta(seconds=ttl)
    for row in rows:
        row.status = SEAT_HELD
        row.held_by = customer_id
        row.hold_key = hold_key
        row.hold_expires_at = expires_at
    db.session.commit()

    return {
        "hold_key": hold_key,
        "event_id": event_id,
        "expires_at": expires_at.isoformat(),
        "ttl_seconds": ttl,
        "seats": [r.to_dict() for r in rows],
    }, None


def release_hold(hold_key, customer_id):
    """Let a customer voluntarily give up their own hold before it expires."""
    query = SeatStatus.query.filter(SeatStatus.hold_key == hold_key).order_by(SeatStatus.seat_id.asc())
    rows = lock_for_update(query).all()

    if not rows:
        db.session.rollback()
        return None, (404, "hold not found (it may already have expired or been used)")
    if any(r.held_by != customer_id for r in rows):
        db.session.rollback()
        return None, (403, "this hold does not belong to you")

    for row in rows:
        row.status = SEAT_AVAILABLE
        row.held_by = None
        row.hold_key = None
        row.hold_expires_at = None
    db.session.commit()
    return {"released_seats": len(rows)}, None


def release_expired_holds():
    """Scheduler target: sweep every hold past its TTL back to 'available'."""
    now = _now()
    query = SeatStatus.query.filter(
        SeatStatus.status == SEAT_HELD,
        SeatStatus.hold_expires_at.isnot(None),
        SeatStatus.hold_expires_at <= now,
    )
    rows = lock_for_update(query).all()
    for row in rows:
        row.status = SEAT_AVAILABLE
        row.held_by = None
        row.hold_key = None
        row.hold_expires_at = None
    if rows:
        db.session.commit()
    return len(rows)


def checkout_uncommitted(hold_key, customer_id):
    """
    Shared core of checkout(): validates the hold and, if valid, creates the
    Booking + marks seats booked — but does NOT commit or roll back. This lets
    a caller extend the same transaction with its own bookkeeping (specifically
    waitlist_service.claim_offer(), which needs the Waitlist row's status flip
    to land atomically with the booking rather than in a second, separately-
    committed transaction — otherwise expire_stale_offers() could race it and
    briefly mark a just-claimed offer as expired).

    Returns (booking, None, created_now) or (None, (status, message), False).
    Caller is responsible for db.session.commit() / db.session.rollback().
    """
    existing = Booking.query.filter_by(hold_key=hold_key).first()
    if existing:
        return existing, None, False

    query = SeatStatus.query.filter(SeatStatus.hold_key == hold_key).order_by(SeatStatus.seat_id.asc())
    rows = lock_for_update(query).all()

    if not rows:
        return None, (404, "hold not found (it may have expired or already been used)"), False

    now = _now()
    for row in rows:
        if row.status != SEAT_HELD:
            return None, (409, "hold is no longer valid"), False
        if row.held_by != customer_id:
            return None, (403, "this hold does not belong to you"), False
        if row.hold_expires_at is None or row.hold_expires_at <= now:
            return None, (410, "hold has expired"), False

    event_id = rows[0].event_id
    pricing = {p.category_id: p.price for p in EventPricing.query.filter_by(event_id=event_id).all()}
    missing_price = [_seat_label(r.seat) for r in rows if r.seat is None or r.seat.category_id not in pricing]
    if missing_price:
        return None, (409, f"no price set for seat(s): {', '.join(missing_price)}"), False

    total = sum(pricing[row.seat.category_id] for row in rows)

    booking = Booking(
        event_id=event_id, customer_id=customer_id, total=total,
        status=BOOKING_CONFIRMED, hold_key=hold_key,
    )
    db.session.add(booking)
    db.session.flush()  # assigns booking.id for the booking_seats rows below

    for row in rows:
        db.session.add(BookingSeat(booking_id=booking.id, seat_id=row.seat_id, label=_seat_label(row.seat)))
        row.status = SEAT_BOOKED
        row.held_by = None
        row.hold_key = None
        row.hold_expires_at = None

    return booking, None, True


def checkout(hold_key, customer_id):
    """
    Convert a live hold into a confirmed Booking. Idempotent: replaying the same
    hold_key after it has already been consumed returns the existing booking
    instead of erroring or double-booking.

    Returns (booking, None, created_now) on success, or (None, (status, message), False).
    """
    booking, error, created = checkout_uncommitted(hold_key, customer_id)
    if error:
        db.session.rollback()
        return None, error, False
    db.session.commit()
    if created:
        # Fresh booking only — never re-send on an idempotent replay.
        from app.services.ticket_service import send_booking_confirmation_email
        send_booking_confirmation_email(booking)
    return booking, None, created


def cancel_booking(booking_id, customer_id):
    """
    Cancel a customer's own confirmed booking, freeing its seats back to
    'available' and offering them to the waitlist for their category, if any.
    (app/services/waitlist_service.py lands in the next phase — this lazy
    import mirrors the pattern already used in app/scheduler.py, so cancellation
    works today and starts notifying the waitlist the moment that module exists.)
    """
    booking = Booking.query.filter_by(id=booking_id, customer_id=customer_id).first()
    if not booking:
        return None, (404, "not_found")
    if booking.status == BOOKING_CANCELLED:
        return booking, None  # already cancelled — idempotent no-op

    seat_ids = [bs.seat_id for bs in booking.seats]
    query = (
        SeatStatus.query
        .filter(SeatStatus.event_id == booking.event_id, SeatStatus.seat_id.in_(seat_ids))
        .order_by(SeatStatus.seat_id.asc())
    )
    rows = lock_for_update(query).all()

    booking.status = BOOKING_CANCELLED
    booking.cancelled_at = _now()

    freed_category_ids = set()
    for row in rows:
        row.status = SEAT_AVAILABLE
        row.held_by = None
        row.hold_key = None
        row.hold_expires_at = None
        if row.seat:
            freed_category_ids.add(row.seat.category_id)

    db.session.commit()

    try:
        from app.services.waitlist_service import offer_next_in_line
        for category_id in freed_category_ids:
            offer_next_in_line(booking.event_id, category_id)
    except ImportError:
        pass

    return booking, None
