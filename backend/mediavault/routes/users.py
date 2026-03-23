from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import auth_required
from ..extensions import db
from ..models import User
from ..services.serializers import serialize_user

bp = Blueprint("users", __name__)


@bp.get("")
@auth_required(admin=True)
def list_users():
    users = User.query.order_by(User.created_at.asc()).all()
    return jsonify({"items": [serialize_user(user) for user in users]})


@bp.post("")
@auth_required(admin=True)
def create_user():
    payload = request.get_json(force=True) or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    display_name = (payload.get("displayName") or username).strip()
    role = payload.get("role") or "user"
    if len(username) < 3 or len(password) < 8:
        return jsonify({"error": "Username or password is too short"}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Username already exists"}), 400

    user = User(username=username, display_name=display_name, role=role, is_active=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({"item": serialize_user(user)}), 201


@bp.patch("/<int:user_id>")
@auth_required(admin=True)
def update_user(user_id: int):
    user = User.query.get_or_404(user_id)
    payload = request.get_json(force=True) or {}
    if "displayName" in payload:
        user.display_name = payload["displayName"].strip() or user.display_name
    if "role" in payload:
        user.role = payload["role"]
    if "isActive" in payload:
        user.is_active = bool(payload["isActive"])
    if payload.get("password"):
        user.set_password(payload["password"])
    db.session.commit()
    return jsonify({"item": serialize_user(user)})
