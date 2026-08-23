from functools import wraps
from flask import jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt, get_jwt_identity
from app.models import User


def role_required(*allowed_roles):
    """Require a valid JWT whose 'role' claim is in allowed_roles."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            claims = get_jwt()
            if claims.get("role") not in allowed_roles:
                return jsonify({"error": "forbidden", "message": "Insufficient role"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def current_user():
    """Load the User row for the current JWT identity, or None."""
    uid = get_jwt_identity()
    if uid is None:
        return None
    return User.query.get(int(uid))
