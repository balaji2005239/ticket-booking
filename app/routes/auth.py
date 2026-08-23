from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required
from app.extensions import db
from app.models import User, ROLES, ROLE_CUSTOMER
from app.utils.auth import current_user

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


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
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "conflict", "message": "email already registered"}), 409

    user = User(name=name, email=email, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    token = create_access_token(identity=str(user.id), additional_claims={"role": user.role})
    return jsonify({"token": token, "user": user.to_dict()}), 201


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "unauthorized", "message": "invalid credentials"}), 401

    token = create_access_token(identity=str(user.id), additional_claims={"role": user.role})
    return jsonify({"token": token, "user": user.to_dict()}), 200


@auth_bp.get("/me")
@jwt_required()
def me():
    user = current_user()
    if not user:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"user": user.to_dict()}), 200
