import logging
import os
from flask import Flask, jsonify
from flask_cors import CORS
from config import Config
from app.extensions import db, jwt

# Plain HTML/CSS/JS frontend (see PROJECT_BRIEF.md's architecture decisions —
# no React/Vite). Served directly by this Flask app by default; the frontend
# is still just static files, so it can equally be pointed at a separate
# static host (Netlify, S3, ...) by editing API_BASE in frontend/js/api.js.
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")


def create_app(config_class=Config):
    app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
    app.config.from_object(config_class)

    # Flask's app.logger defaults to WARNING in production (no debug mode) —
    # discovered the hard way: current_app.logger.info(...) calls throughout
    # this codebase (email send attempts, etc.) were being silently dropped
    # by the logging module itself, never reaching Render's log stream, even
    # though a handler was present. Without this, "check the logs" is a dead
    # end for anything below WARNING.
    app.logger.setLevel(logging.INFO)

    CORS(app, resources={r"/api/*": {"origins": "*"}})
    db.init_app(app)
    jwt.init_app(app)

    # Import models so create_all sees them
    from app import models  # noqa: F401

    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.venues import venues_bp
    from app.routes.events import events_bp
    from app.routes.browse import browse_bp
    from app.routes.bookings import bookings_bp
    from app.routes.waitlist import waitlist_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(venues_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(browse_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(waitlist_bp)

    # Health check
    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"}), 200

    # Frontend entry point (everything else under frontend/ — css/, js/, other
    # .html pages — is auto-served by Flask's static handling since static_url_path
    # is "" above).
    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    # JSON error handlers
    @app.errorhandler(404)
    def not_found(_):
        return jsonify({"error": "not_found"}), 404

    @app.errorhandler(500)
    def server_error(_):
        return jsonify({"error": "server_error"}), 500

    # Create tables (simple deploy; no migrations)
    with app.app_context():
        db.create_all()

    # Start background expiry scheduler unless disabled (e.g. during tests)
    if os.getenv("DISABLE_SCHEDULER") != "1":
        from app.scheduler import init_scheduler
        init_scheduler(app)

    return app
