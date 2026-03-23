from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import auth_required, get_current_user
from ..extensions import db
from ..models import Tag
from ..services.serializers import serialize_tag
from ..services.tag_styles import (
    encode_gradient_colors,
    normalize_color,
    normalize_gradient_angle,
    normalize_gradient_colors,
)
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
    gradient_colors = normalize_gradient_colors(
        payload.get("gradientColors"),
        fallback_start=payload.get("colorStart"),
        fallback_end=payload.get("colorEnd"),
    )
    color_start = normalize_color(payload.get("colorStart"), gradient_colors[0]) or gradient_colors[0]
    color_end = normalize_color(payload.get("colorEnd"), gradient_colors[-1]) or gradient_colors[-1]
    tag = Tag(
        name=name,
        slug=_unique_slug(name),
        description=payload.get("description"),
        style_mode=payload.get("styleMode") or "gradient",
        color_start=color_start,
        color_end=color_end,
        gradient_colors=encode_gradient_colors(gradient_colors),
        gradient_angle=normalize_gradient_angle(payload.get("gradientAngle")),
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
    if {"colorStart", "colorEnd", "gradientColors"} & payload.keys():
        gradient_colors = normalize_gradient_colors(
            payload.get("gradientColors", tag.gradient_colors),
            fallback_start=payload.get("colorStart", tag.color_start),
            fallback_end=payload.get("colorEnd", tag.color_end),
        )
        tag.color_start = normalize_color(payload.get("colorStart"), gradient_colors[0]) or gradient_colors[0]
        tag.color_end = normalize_color(payload.get("colorEnd"), gradient_colors[-1]) or gradient_colors[-1]
        tag.gradient_colors = encode_gradient_colors(gradient_colors)
    if "gradientAngle" in payload:
        tag.gradient_angle = normalize_gradient_angle(payload["gradientAngle"])
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
