from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import auth_required, get_current_user
from ..extensions import db
from ..models import Tag
from ..services.serializers import serialize_tag
from ..utils import slugify

bp = Blueprint("tags", __name__)


def _unique_slug(name: str, existing_id: int | None = None) -> str:
    base = slugify(name)
    slug = base
    index = 2
    while True:
        query = Tag.query.filter_by(slug=slug)
        if existing_id is not None:
            query = query.filter(Tag.id != existing_id)
        if not query.first():
            return slug
        slug = f"{base}-{index}"
        index += 1


@bp.get("")
@auth_required()
def list_tags():
    tags = Tag.query.order_by(Tag.name.asc()).all()
    return jsonify({"items": [serialize_tag(tag) for tag in tags]})


@bp.post("")
@auth_required()
def create_tag():
    payload = request.get_json(force=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Tag name is required"}), 400
    tag = Tag(
        name=name,
        slug=_unique_slug(name),
        description=payload.get("description"),
        style_mode=payload.get("styleMode") or "gradient",
        color_start=payload.get("colorStart") or "#7c3aed",
        color_end=payload.get("colorEnd") or "#10b981",
        text_color=payload.get("textColor") or "#f8fafc",
        avatar_url=payload.get("avatarUrl"),
        created_by_id=get_current_user().id,
    )
    db.session.add(tag)
    db.session.commit()
    return jsonify({"item": serialize_tag(tag)}), 201


@bp.patch("/<int:tag_id>")
@auth_required()
def update_tag(tag_id: int):
    tag = Tag.query.get_or_404(tag_id)
    payload = request.get_json(force=True) or {}
    if "name" in payload and payload["name"].strip():
        tag.name = payload["name"].strip()
        tag.slug = _unique_slug(tag.name, existing_id=tag.id)
    if "description" in payload:
        tag.description = payload["description"]
    if "styleMode" in payload:
        tag.style_mode = payload["styleMode"]
    if "colorStart" in payload:
        tag.color_start = payload["colorStart"]
    if "colorEnd" in payload:
        tag.color_end = payload["colorEnd"]
    if "textColor" in payload:
        tag.text_color = payload["textColor"]
    if "avatarUrl" in payload:
        tag.avatar_url = payload["avatarUrl"]
    db.session.commit()
    return jsonify({"item": serialize_tag(tag)})


@bp.delete("/<int:tag_id>")
@auth_required()
def delete_tag(tag_id: int):
    tag = Tag.query.get_or_404(tag_id)
    db.session.delete(tag)
    db.session.commit()
    return jsonify({"ok": True})
