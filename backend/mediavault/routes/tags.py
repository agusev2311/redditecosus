from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import auth_required, get_current_user
from ..extensions import db
from ..models import Tag
from ..services.serializers import serialize_tag
from ..services.tag_media import (
    cleanup_avatar_reference,
    media_query_for_user,
    store_tag_avatar,
    stream_tag_asset,
    tag_query_for_user,
)
from ..services.tag_styles import (
    encode_gradient_colors,
    normalize_color,
    normalize_gradient_angle,
    normalize_gradient_colors,
)
from ..utils import slugify

bp = Blueprint("tags", __name__)


def _tag_scope():
    return tag_query_for_user(get_current_user())


def _normalize_avatar_ref(raw_value: str | None) -> str | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    if value.startswith("media:"):
        try:
            media_id = int(value.split(":", 1)[1])
        except ValueError:
            return None
        media = media_query_for_user(get_current_user()).filter_by(id=media_id, media_type="image").first()
        return f"media:{media.id}" if media else None
    if value.startswith("asset:"):
        return value
    return value


def _unique_slug(name: str, existing_id: int | None = None) -> str:
    base = slugify(name)
    slug = base
    index = 2
    while True:
        query = _tag_scope().filter_by(slug=slug)
        if existing_id is not None:
            query = query.filter(Tag.id != existing_id)
        if not query.first():
            return slug
        slug = f"{base}-{index}"
        index += 1


@bp.get("")
@auth_required()
def list_tags():
    tags = _tag_scope().order_by(Tag.name.asc()).all()
    return jsonify({"items": [serialize_tag(tag) for tag in tags]})


@bp.post("/avatar-upload")
@auth_required()
def upload_tag_avatar():
    incoming = request.files.get("file")
    if not incoming:
        return jsonify({"error": "Missing file"}), 400
    try:
        avatar_ref = store_tag_avatar(incoming)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    temp_tag = Tag(avatar_url=avatar_ref)
    return jsonify({"avatarRef": avatar_ref, "avatarUrl": serialize_tag(temp_tag)["avatarUrl"]}), 201


@bp.get("/avatar-asset/<path:asset_key>")
@auth_required()
def stream_tag_asset_file(asset_key: str):
    return stream_tag_asset(asset_key)


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
        avatar_url=_normalize_avatar_ref(payload.get("avatarUrl")),
        created_by_id=get_current_user().id,
    )
    db.session.add(tag)
    db.session.commit()
    return jsonify({"item": serialize_tag(tag)}), 201


@bp.patch("/<int:tag_id>")
@auth_required()
def update_tag(tag_id: int):
    tag = _tag_scope().filter_by(id=tag_id).first_or_404()
    payload = request.get_json(force=True) or {}
    previous_avatar = tag.avatar_url
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
        tag.avatar_url = _normalize_avatar_ref(payload["avatarUrl"])
    db.session.commit()
    if previous_avatar != tag.avatar_url:
        cleanup_avatar_reference(previous_avatar, tag_id_to_ignore=tag.id)
    return jsonify({"item": serialize_tag(tag)})


@bp.delete("/<int:tag_id>")
@auth_required()
def delete_tag(tag_id: int):
    tag = _tag_scope().filter_by(id=tag_id).first_or_404()
    previous_avatar = tag.avatar_url
    db.session.delete(tag)
    db.session.commit()
    cleanup_avatar_reference(previous_avatar, tag_id_to_ignore=tag.id)
    return jsonify({"ok": True})
