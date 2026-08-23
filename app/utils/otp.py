import secrets
from datetime import datetime, timedelta, timezone


def generate_otp():
    """6-digit numeric code, cryptographically random (not Mersenne Twister —
    this guards actual account access, same bar as hold_key/offer_token
    elsewhere, which use uuid4's OS-backed randomness)."""
    return f"{secrets.randbelow(10 ** 6):06d}"


def otp_expiry(ttl_seconds):
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=ttl_seconds)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)
