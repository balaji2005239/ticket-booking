from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db

# Role constants
ROLE_CUSTOMER = "customer"
ROLE_ORGANISER = "organiser"
ROLE_ADMIN = "admin"
ROLES = (ROLE_CUSTOMER, ROLE_ORGANISER, ROLE_ADMIN)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_CUSTOMER)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Email OTP verification (customer/organiser self-registration only — admins
    # are seeded directly by a trusted operator, never through /register, so
    # they're exempt; see role_required-style check in routes/auth.py's login()).
    # otp_code/otp_expires_at are populated only while a verification is pending,
    # same pattern as SeatStatus.hold_key/hold_expires_at.
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    otp_code = db.Column(db.String(6))
    otp_expires_at = db.Column(db.DateTime)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "role": self.role,
            "email_verified": self.email_verified,
        }
