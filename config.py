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

    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "noreply@example.com")
    SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Ticket Booking")

    FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5500")
