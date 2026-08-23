"""
QR ticket generation + booking confirmation email.

Called right after a booking is freshly confirmed — from seat_service.checkout()
and waitlist_service.claim_offer(), both gated on created=True so an idempotent
replay never sends a duplicate ticket email.

Best-effort: a QR/email failure must never fail the booking itself. send_email()
already fails soft (logs + returns False when SMTP isn't configured); this module
catches anything else defensively too.
"""
import io

import qrcode
from flask import current_app

from app.models import User
from app.utils.email import send_email


def generate_qr_png(data: str) -> bytes:
    """QR-encode `data` (the booking ref, per the brief) as a PNG."""
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def send_booking_confirmation_email(booking):
    """Build and send the 'booking confirmed' email with the QR ticket attached."""
    try:
        customer = User.query.get(booking.customer_id)
        event = booking.event
        if not customer or not event:
            return False

        qr_bytes = generate_qr_png(booking.ref)
        seats = ", ".join(bs.label for bs in booking.seats if bs.label) or "—"
        venue_name = event.venue.name if event.venue else ""
        starts_at = event.starts_at.strftime("%a, %d %b %Y %I:%M %p") if event.starts_at else ""

        html = f"""
        <p>Hi {customer.name},</p>
        <p>Your booking is confirmed!</p>
        <table cellpadding="4">
          <tr><td><strong>Event</strong></td><td>{event.title}</td></tr>
          <tr><td><strong>Venue</strong></td><td>{venue_name}</td></tr>
          <tr><td><strong>When</strong></td><td>{starts_at}</td></tr>
          <tr><td><strong>Seats</strong></td><td>{seats}</td></tr>
          <tr><td><strong>Total</strong></td><td>&#8377;{float(booking.total):.2f}</td></tr>
          <tr><td><strong>Booking Ref</strong></td><td>{booking.ref}</td></tr>
        </table>
        <p>Your QR code ticket is attached — show it at entry.</p>
        """
        return send_email(
            customer.email,
            f"Booking confirmed: {event.title} ({booking.ref})",
            html,
            attachments=[(f"ticket-{booking.ref}.png", qr_bytes, "png")],
        )
    except Exception as e:  # noqa: BLE001 — never let a ticket/email bug break the booking flow
        current_app.logger.error("booking confirmation email failed for booking %s: %s", booking.id, e)
        return False
