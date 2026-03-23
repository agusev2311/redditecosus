from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from flask import current_app

from ..extensions import db
from ..models import MediaItem, Tag
from .storage import build_streaming_response, calculate_sha256, store_preview

TAG_AVATAR_MEDIA_PREFIX = "media:"
TAG_AVATAR_ASSET_PREFIX = "asset:"


def tag_query_for_user(user):
    query = Tag.query
    if user:
        query = query.filter_by(created_by_id=user.id)
    return query


def media_query_for_user(user):
    query = MediaItem.query
    if user:
        query = query.filter_by(owner_id=user.id)
    return query


def classify_avatar_source(raw_value: str | None) -> str:
    value = (raw_value or "").strip()
    if not value:
        return "none"
    if value.startswith(TAG_AVATAR_MEDIA_PREFIX):
        return "media"
    if value.startswith(TAG_AVATAR_ASSET_PREFIX):
        return "upload"
    return "external"


def _avatar_asset_path(raw_value: str | None) -> str | None:
    value = (raw_value or "").strip()
    if not value.startswith(TAG_AVATAR_ASSET_PREFIX):
        return None
    return value[len(TAG_AVATAR_ASSET_PREFIX) :]


def avatar_media_id(raw_value: str | None) -> int | None:
    value = (raw_value or "").strip()
    if not value.startswith(TAG_AVATAR_MEDIA_PREFIX):
        return None
    try:
        return int(value[len(TAG_AVATAR_MEDIA_PREFIX) :])
    except ValueError:
        return None


def store_tag_avatar(file_storage) -> str:
    suffix = Path(file_storage.filename or "tag-avatar").suffix or ".jpg"
    with tempfile.NamedTemporaryFile(
        delete=False,
        dir=current_app.config["IMPORTS_ROOT"],
        suffix=suffix,
    ) as source_handle:
        source_path = Path(source_handle.name)
        file_storage.save(source_handle)

    processed_fd, processed_name = tempfile.mkstemp(dir=current_app.config["IMPORTS_ROOT"], suffix=".jpg")
    os.close(processed_fd)
    processed_path = Path(processed_name)
    try:
        with Image.open(source_path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((768, 768))
            image.save(processed_path, format="JPEG", quality=88, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        processed_path.unlink(missing_ok=True)
        raise ValueError("Unsupported avatar image") from exc
    finally:
        source_path.unlink(missing_ok=True)

    hash_hex = calculate_sha256(processed_path)
    relative_path = store_preview(processed_path, hash_hex)
    return f"{TAG_AVATAR_ASSET_PREFIX}{relative_path}"


def stream_tag_asset(asset_key: str):
    return build_streaming_response(
        asset_key,
        bool(current_app.config["MEDIA_ENCRYPTION_PASSPHRASE"]),
        "image/jpeg",
    )


def resolve_avatar_reference(raw_value: str | None, url_builder) -> tuple[str | None, str, int | None]:
    value = (raw_value or "").strip()
    source_type = classify_avatar_source(value)
    if source_type == "media":
        media_id = avatar_media_id(value)
        if media_id is None:
            return None, "none", None
        return url_builder("media.stream_preview", media_id=media_id), source_type, media_id
    if source_type == "upload":
        asset_key = _avatar_asset_path(value)
        if not asset_key:
            return None, "none", None
        return url_builder("tags.stream_tag_asset_file", asset_key=asset_key), source_type, None
    if source_type == "external":
        return value, source_type, None
    return None, "none", None


def cleanup_avatar_reference(raw_value: str | None, tag_id_to_ignore: int | None = None) -> None:
    value = (raw_value or "").strip()
    if not value.startswith(TAG_AVATAR_ASSET_PREFIX):
        return
    query = Tag.query.filter_by(avatar_url=value)
    if tag_id_to_ignore is not None:
        query = query.filter(Tag.id != tag_id_to_ignore)
    if query.count():
        return

    asset_key = _avatar_asset_path(value)
    if not asset_key:
        return
    if MediaItem.query.filter_by(preview_path=asset_key).count():
        return
    (Path(current_app.config["DATA_ROOT"]) / asset_key).unlink(missing_ok=True)
