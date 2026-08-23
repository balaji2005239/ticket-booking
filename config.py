import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


def _db_url():
    url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ticketing")
    # Render/Heroku sometimes hand out the legacy "postgres://" scheme
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=12)

    SQLALCHEMY_DATABASE_URI = _db_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    HOLD_TTL_SECONDS = int(os.getenv("HOLD_TTL_SECONDS", 600))
    OFFER_TTL_SECONDS = int(os.getenv("OFFER_TTL_SECONDS", 600))
    SCHEDULER_INTERVAL_SECONDS = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", 30))
    OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", 600))

    # Email via Brevo's HTTP API (see app/utils/email.py's docstring for why
    # this isn't raw SMTP — Render blocks outbound SMTP traffic entirely).
    # BREVO_API_KEY comes from Brevo's dashboard under SMTP & API -> API Keys
    # (a different credential from an SMTP key, despite the similar naming).
    BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
    EMAIL_FROM_ADDRESS = os.getenv("EMAIL_FROM_ADDRESS", "noreply@example.com")
    EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Ticket Booking")

    FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5500")
