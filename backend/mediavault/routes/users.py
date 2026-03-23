from __future__ import annotations

from sqlalchemy import func
from flask import Blueprint, jsonify, request

from ..auth import auth_required
from ..extensions import db
from ..models import MediaItem, Tag, UploadBatch, User
from ..services.serializers import serialize_user

bp = Blueprint("users", __name__)


@bp.get("")
@auth_required(admin=True)
def list_users():
    users = User.query.order_by(User.created_at.asc()).all()
    media_stats = {
        row.owner_id: {"mediaCount": row.media_count, "uploadedBytes": row.uploaded_bytes}
        for row in (
            db.session.query(
                MediaItem.owner_id,
                func.count(MediaItem.id).label("media_count"),
                func.coalesce(func.sum(MediaItem.size_bytes), 0).label("uploaded_bytes"),
            )
            .group_by(MediaItem.owner_id)
            .all()
        )
    }
    batch_stats = {
        row.owner_id: row.batch_count
        for row in (
            db.session.query(
                UploadBatch.owner_id,
                func.count(UploadBatch.id).label("batch_count"),
            )
            .group_by(UploadBatch.owner_id)
            .all()
        )
    }
    tag_stats = {
        row.created_by_id: row.tag_count
        for row in (
            db.session.query(
                Tag.created_by_id,
                func.count(Tag.id).label("tag_count"),
            )
            .group_by(Tag.created_by_id)
            .all()
        )
        if row.created_by_id is not None
    }
    return jsonify(
        {
            "items": [
                {
                    **serialize_user(user),
                    "mediaCount": media_stats.get(user.id, {}).get("mediaCount", 0),
                    "uploadedBytes": media_stats.get(user.id, {}).get("uploadedBytes", 0),
                    "batchCount": batch_stats.get(user.id, 0),
                    "tagCount": tag_stats.get(user.id, 0),
                }
                for user in users
            ]
        }
    )


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
