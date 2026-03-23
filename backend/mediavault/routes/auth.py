from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import auth_required, create_auth_token, get_current_user
from ..models import User
from ..services.serializers import serialize_user

bp = Blueprint("auth", __name__)


@bp.post("/login")
def login():
    payload = request.get_json(force=True) or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid credentials"}), 401
    if not user.is_active:
        return jsonify({"error": "Account is disabled"}), 403
    return jsonify({"token": create_auth_token(user), "user": serialize_user(user)})


@bp.get("/me")
@auth_required()
def me():
    return jsonify({"user": serialize_user(get_current_user())})
