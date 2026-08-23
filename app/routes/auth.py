from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required
from app.extensions import db
from app.models import User, ROLES, ROLE_CUSTOMER, ROLE_ADMIN
from app.utils.auth import current_user
from app.utils.otp import generate_otp, otp_expiry, now as otp_now
from app.utils.email import send_email

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _issue_token(user):
    token = create_access_token(identity=str(user.id), additional_claims={"role": user.role})
    return jsonify({"token": token, "user": user.to_dict()}), 200


def _send_otp(user):
    """Generate a fresh OTP, persist it, and email it. Fails soft on the
    email side (send_email() already does) — the code is still valid and
    can be requested again via /resend-otp if the email doesn't arrive."""
    code = generate_otp()
    user.otp_code = code
    user.otp_expires_at = otp_expiry(current_app.config["OTP_TTL_SECONDS"])
    db.session.commit()

    minutes = max(current_app.config["OTP_TTL_SECONDS"] // 60, 1)
    html = (
        f"<p>Hi {user.name},</p>"
        f"<p>Your verification code is:</p>"
        f"<p style=\"font-size:28px;font-weight:700;letter-spacing:6px;\">{code}</p>"
        f"<p>Enter it within {minutes} minutes to verify your account. If you didn't "
        f"request this, you can ignore this email.</p>"
    )
    send_email(user.email, "Verify your email — Ticket Booking", html)


@auth_bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    role = (data.get("role") or ROLE_CUSTOMER).strip().lower()

    if not name or not email or not password:
        return jsonify({"error": "validation", "message": "name, email, password are required"}), 400
    if role not in ROLES:
        return jsonify({"error": "validation", "message": f"role must be one of {ROLES}"}), 400
    # Admins are seeded, not self-registered
    if role == "admin":
        return jsonify({"error": "forbidden", "message": "admin accounts cannot self-register"}), 403

    existing = User.query.filter_by(email=email).first()
    if existing:
        if existing.email_verified:
            return jsonify({"error": "conflict", "message": "email already registered"}), 409
        # Unverified account retrying registration (lost the first code, typo'd
        # something) — update details and send a fresh code rather than hard
        # blocking. Safe: the OTP still only reaches whoever controls the inbox.
        existing.name = name
        existing.set_password(password)
        existing.role = role
        user = existing
    else:
        user = User(name=name, email=email, role=role)
        user.set_password(password)
        db.session.add(user)
    db.session.commit()

    _send_otp(user)
    return jsonify({
        "message": "Registered. Check your email for a verification code.",
        "email": user.email,
    }), 201


@auth_bp.post("/verify-email")
def verify_email():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    otp = (data.get("otp") or "").strip()

    if not email or not otp:
        return jsonify({"error": "validation", "message": "email and otp are required"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "not_found", "message": "no account for this email"}), 404

    if user.email_verified:
        # Idempotent: e.g. a reloaded page resubmitting after success already
        # landed — log them in instead of erroring.
        return _issue_token(user)

    if not user.otp_code or user.otp_code != otp:
        return jsonify({"error": "validation", "message": "invalid code"}), 400
    if not user.otp_expires_at or user.otp_expires_at <= otp_now():
        return jsonify({"error": "expired", "message": "code expired — request a new one"}), 410

    user.email_verified = True
    user.otp_code = None
    user.otp_expires_at = None
    db.session.commit()

    return _issue_token(user)


@auth_bp.post("/resend-otp")
def resend_otp():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "validation", "message": "email is required"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "not_found", "message": "no account for this email"}), 404
    if user.email_verified:
        return jsonify({"error": "conflict", "message": "email already verified"}), 409

    _send_otp(user)
    return jsonify({"message": "Verification code resent."}), 200


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "unauthorized", "message": "invalid credentials"}), 401

    # Admins are seeded directly by a trusted operator, never through
    # /register, so they never go through OTP verification — exempt.
    # Self-registered roles (customer/organiser) must verify.
    if user.role != ROLE_ADMIN and not user.email_verified:
        return jsonify({
            "error": "email_not_verified",
            "message": "please verify your email before logging in",
        }), 403

    return _issue_token(user)


@auth_bp.get("/me")
@jwt_required()
def me():
    user = current_user()
    if not user:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"user": user.to_dict()}), 200
