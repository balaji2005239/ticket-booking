"""
Waitlist: FIFO queue per (event, seat_category). When a seat in that category
frees up (currently: only via cancel_booking() in seat_service.py — see the
note below), the next waiting entry gets a time-limited offer instead of the
seat just going back into the general pool.

An "offer" reuses the exact same seat_status hold mechanism a normal customer
hold uses: the seat flips to 'held', with the Waitlist entry's offer_token as
its hold_key. That means hold_seats()/checkout() already treat an offered seat
as correctly unavailable to everyone else, and claiming an offer is literally
a checkout() with the offer_token as the hold_key — see claim_offer().

expire_stale_offers() is the scheduler target (app/scheduler.py) that sweeps
offers past OFFER_TTL_SECONDS: frees the seat and cascades to the next waiting
entry in the same call, so "offered to next in line" happens within the same
sweep rather than waiting an extra scheduler cycle.

Race handling: every Waitlist row this module writes to is SELECT ... FOR
UPDATE'd first (via app.utils.locking.lock_for_update, same helper
seat_service.py uses), so a claim landing at the same moment the expiry sweep
is processing that exact offer can't leave the entry in the wrong terminal
status — whichever transaction's lock lands first wins, and the other sees the
already-updated status and no-ops. The one intentionally-accepted gap: picking
"the next waiting entry" for a category isn't perfectly linearizable if two
cancellations for the *same* category race at the exact same instant (a
single-instance-scale trade-off, consistent with this project's other scope
decisions — see PROJECT_BRIEF.md's "How This Scales" trade-offs). It cannot
cause a double-booked seat (seat_status locking still guarantees that); the
worst case is a seat sitting offered a beat longer than ideal before its own
TTL sweep frees it.
"""
import uuid
from datetime import datetime, timedelta, timezone

from flask import current_app

from app.extensions import db
from app.models import (
    Waitlist, WL_WAITING, WL_OFFERED, WL_CONVERTED, WL_EXPIRED,
    Event, SeatCategory, Seat, SeatStatus, SEAT_AVAILABLE, SEAT_HELD,
    User,
)
from app.utils.locking import lock_for_update
from app.utils.email import send_email
from app.services.seat_service import checkout_uncommitted


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _seat_label(seat):
    return f"{seat.row_label}{seat.seat_number}" if seat else None


def join_waitlist(event_id, category_id, customer_id):
    """
    Join the FIFO waitlist for a specific (event, category). Only allowed when
    the category actually has zero available seats right now — otherwise the
    customer should just book directly.
    Returns (entry, None) or (None, (status_code, message)).
    """
    event = Event.query.get(event_id)
    if not event:
        return None, (404, "event not found")

    category = SeatCategory.query.filter_by(id=category_id, venue_id=event.venue_id).first()
    if not category:
        return None, (400, "category_id does not belong to this event's venue")

    available_count = (
        SeatStatus.query
        .join(Seat, Seat.id == SeatStatus.seat_id)
        .filter(SeatStatus.event_id == event_id, Seat.category_id == category_id, SeatStatus.status == SEAT_AVAILABLE)
        .count()
    )
    if available_count > 0:
        return None, (409, "seats are still available in this category — book directly instead of joining the waitlist")

    existing = Waitlist.query.filter(
        Waitlist.event_id == event_id,
        Waitlist.category_id == category_id,
        Waitlist.customer_id == customer_id,
        Waitlist.status.in_([WL_WAITING, WL_OFFERED]),
    ).first()
    if existing:
        return None, (409, "already on the waitlist for this event/category")

    entry = Waitlist(event_id=event_id, category_id=category_id, customer_id=customer_id, status=WL_WAITING)
    db.session.add(entry)
    db.session.commit()
    return entry, None


def offer_next_in_line(event_id, category_id):
    """
    While there's at least one available seat in this category and at least one
    'waiting' entry in the FIFO queue, create a time-limited offer for the next
    entry: lock a seat and flip it to 'held' under the offer's token, lock the
    waitlist entry and flip it to 'offered', email the customer a claim link.
    Called by cancel_booking() (per freed category) and by
    expire_stale_offers() (to cascade a lapsed offer to the next person).
    """
    while True:
        entry_query = (
            Waitlist.query
            .filter_by(event_id=event_id, category_id=category_id, status=WL_WAITING)
            .order_by(Waitlist.created_at.asc())
        )
        entry = lock_for_update(entry_query).first()
        if not entry:
            db.session.rollback()
            return

        seat_query = (
            SeatStatus.query
            .join(Seat, Seat.id == SeatStatus.seat_id)
            .filter(SeatStatus.event_id == event_id, Seat.category_id == category_id, SeatStatus.status == SEAT_AVAILABLE)
            .order_by(Seat.row_label.asc(), Seat.seat_number.asc())
        )
        seat_row = lock_for_update(seat_query).first()
        if not seat_row:
            db.session.rollback()
            return

        ttl = current_app.config["OFFER_TTL_SECONDS"]
        now = _now()
        token = uuid.uuid4().hex
        expires_at = now + timedelta(seconds=ttl)

        seat_row.status = SEAT_HELD
        seat_row.held_by = entry.customer_id
        seat_row.hold_key = token
        seat_row.hold_expires_at = expires_at

        entry.status = WL_OFFERED
        entry.offer_token = token
        entry.offer_seat_id = seat_row.seat_id
        entry.offer_expires_at = expires_at

        db.session.commit()
        _send_offer_email(entry, seat_row)
        # loop again: there may be more available seats + waiting entries left


def claim_offer(offer_token, customer_id):
    """
    A waitlisted customer completes their booking via the time-limited offer
    link. This is exactly a checkout() — the offer token IS the seat_status
    hold_key created by offer_next_in_line() — plus flipping the Waitlist entry
    to 'converted', committed together in one transaction (see checkout_uncommitted's
    docstring for why that atomicity matters here).

    Returns (booking, None, created_now) or (None, (status, message), False).
    """
    entry_query = Waitlist.query.filter_by(offer_token=offer_token)
    entry = lock_for_update(entry_query).first()

    if not entry:
        db.session.rollback()
        return None, (404, "offer not found"), False
    if entry.customer_id != customer_id:
        db.session.rollback()
        return None, (403, "this offer does not belong to you"), False
    # WL_CONVERTED is allowed through too: that's exactly what a replay of an
    # already-claimed offer looks like, and checkout_uncommitted() below is what
    # makes that replay idempotent (finds the existing Booking by hold_key
    # instead of erroring). Any other status (waiting/expired/cancelled) means
    # this token was never a live offer or has genuinely lapsed.
    if entry.status not in (WL_OFFERED, WL_CONVERTED):
        db.session.rollback()
        return None, (410, "this offer is no longer valid (expired or already used)"), False

    booking, error, created = checkout_uncommitted(offer_token, customer_id)
    if error:
        db.session.rollback()
        return None, error, False

    if created:
        entry.status = WL_CONVERTED
    db.session.commit()
    if created:
        # Fresh booking only — never re-send on an idempotent replay.
        from app.services.ticket_service import send_booking_confirmation_email
        send_booking_confirmation_email(booking)
    return booking, None, created


def expire_stale_offers():
    """
    Scheduler target: sweep every offer past OFFER_TTL_SECONDS, free its seat,
    mark the entry 'expired', then immediately try to offer that freed seat to
    the next waiting entry in the same category (same sweep, not the next one).
    """
    now = _now()
    stale_ids = [
        w.id for w in Waitlist.query.filter(Waitlist.status == WL_OFFERED, Waitlist.offer_expires_at <= now).all()
    ]

    affected = set()
    for wid in stale_ids:
        entry = lock_for_update(Waitlist.query.filter_by(id=wid)).first()
        # Re-check after acquiring the lock: a concurrent claim_offer() may have
        # already converted this entry between our first query and now.
        if not entry or entry.status != WL_OFFERED:
            continue
        if entry.offer_expires_at is None or entry.offer_expires_at > _now():
            continue

        seat_query = SeatStatus.query.filter(
            SeatStatus.event_id == entry.event_id,
            SeatStatus.seat_id == entry.offer_seat_id,
            SeatStatus.hold_key == entry.offer_token,
        )
        seat_row = lock_for_update(seat_query).first()
        if seat_row and seat_row.status == SEAT_HELD:
            seat_row.status = SEAT_AVAILABLE
            seat_row.held_by = None
            seat_row.hold_key = None
            seat_row.hold_expires_at = None

        entry.status = WL_EXPIRED
        affected.add((entry.event_id, entry.category_id))

    db.session.commit()

    for event_id, category_id in affected:
        offer_next_in_line(event_id, category_id)

    return len(affected)


def _send_offer_email(entry, seat_row):
    """
    Best-effort — send_email() already fails soft, but this function used to
    have no error handling of its own around the lookups/formatting before
    that call, so a bug there would fail *silently*: no exception reaches the
    caller (offer_next_in_line() has no try/except either, so a raise here
    would actually propagate all the way to a 500 on the cancel/claim
    request — which never happened in testing, meaning this path was
    completing without raising) and nothing gets logged either way. Explicit
    logging + a try/except now, matching ticket_service.py's pattern, so
    "did we even try to send this" is never ambiguous again.
    """
    try:
        customer = User.query.get(entry.customer_id)
        event = Event.query.get(entry.event_id)
        if not customer or not event:
            current_app.logger.error(
                "waitlist offer email skipped: customer=%s event=%s not found (entry id=%s)",
                entry.customer_id, entry.event_id, entry.id,
            )
            return False

        base = current_app.config["FRONTEND_BASE_URL"].rstrip("/")
        link = f"{base}/claim-offer.html?token={entry.offer_token}"
        minutes = max(current_app.config["OFFER_TTL_SECONDS"] // 60, 1)
        seat_label = _seat_label(seat_row.seat) or "a seat"

        html = (
            f"<p>Hi {customer.name},</p>"
            f"<p>A seat just opened up for <strong>{event.title}</strong> ({seat_label}) "
            f"and you're next on the waitlist.</p>"
            f'<p><a href="{link}">Claim it here</a> within {minutes} minutes, or it goes '
            f"to the next person in line.</p>"
        )
        current_app.logger.info("Sending waitlist offer email to %s (entry id=%s)", customer.email, entry.id)
        result = send_email(customer.email, f"Seat available: {event.title}", html)
        current_app.logger.info("Waitlist offer email to %s: send_email() returned %s", customer.email, result)
        return result
    except Exception as e:  # noqa: BLE001 — never let an email bug break the offer flow
        current_app.logger.error("waitlist offer email failed (entry id=%s): %s", entry.id, e)
        return False
