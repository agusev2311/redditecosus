from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlalchemy import func, or_

from ..auth import auth_required, get_current_user
from ..extensions import db
from ..models import MediaItem, Tag
from ..services.serializers import serialize_media, serialize_tag
from ..services.storage import (
    build_streaming_response,
    delete_preview_if_unreferenced,
    delete_storage_if_unreferenced,
)

bp = Blueprint("media", __name__)


def _query():
    user = get_current_user()
    query = MediaItem.query
    if not user.is_admin:
        query = query.filter_by(owner_id=user.id)
    return query


def _get_accessible(media_id: int):
    return _query().filter_by(id=media_id).first_or_404()


def _delete_media_item(item: MediaItem) -> None:
    storage_path = item.storage_path
    preview_path = item.preview_path
    same_hash = (
        MediaItem.query.filter(MediaItem.sha256_hash == item.sha256_hash, MediaItem.id != item.id)
        .order_by(MediaItem.is_duplicate.asc(), MediaItem.created_at.asc())
        .all()
    )

    if not item.is_duplicate and same_hash:
        new_canonical = same_hash[0]
        new_canonical.is_duplicate = False
        new_canonical.canonical_media_id = None
        new_canonical.storage_path = item.storage_path
        new_canonical.preview_path = item.preview_path
        new_canonical.is_encrypted = item.is_encrypted
        db.session.flush()
        for sibling in same_hash[1:]:
            sibling.is_duplicate = True
            sibling.canonical_media_id = new_canonical.id
            sibling.storage_path = new_canonical.storage_path
            sibling.preview_path = new_canonical.preview_path
            sibling.is_encrypted = new_canonical.is_encrypted

    db.session.delete(item)
    db.session.flush()
    delete_storage_if_unreferenced(storage_path, media_id_to_ignore=item.id)
    delete_preview_if_unreferenced(preview_path, media_id_to_ignore=item.id)
    db.session.commit()


@bp.get("")
@auth_required()
def list_media():
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("perPage", 30)), 1), 120)
    search = (request.args.get("q") or "").strip()
    media_type = (request.args.get("mediaType") or "").strip()
    duplicates_only = request.args.get("duplicatesOnly") == "1"
    tag_ids = [int(raw) for raw in (request.args.get("tagIds") or "").split(",") if raw.strip().isdigit()]

    query = _query().order_by(MediaItem.created_at.desc())
    if search:
        query = query.outerjoin(MediaItem.tags).filter(
            or_(
                MediaItem.original_filename.ilike(f"%{search}%"),
                MediaItem.note.ilike(f"%{search}%"),
                Tag.name.ilike(f"%{search}%"),
            )
        ).distinct()
    if media_type:
        query = query.filter_by(media_type=media_type)
    if duplicates_only:
        query = query.filter_by(is_duplicate=True)
    if tag_ids:
        query = query.join(MediaItem.tags).filter(Tag.id.in_(tag_ids)).distinct()

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify(
        {
            "items": [serialize_media(item) for item in pagination.items],
            "page": page,
            "perPage": per_page,
            "total": pagination.total,
            "pages": pagination.pages,
        }
    )


@bp.get("/review/next")
@auth_required()
def next_review_item():
    only_untagged = request.args.get("untagged", "1") == "1"
    after_id = request.args.get("afterId", type=int)
    query = _query().order_by(MediaItem.id.asc())
    if only_untagged:
        query = query.filter(~MediaItem.tags.any())
    if after_id:
        candidate = query.filter(MediaItem.id > after_id).first()
    else:
        candidate = query.first()
    return jsonify(
        {
            "item": serialize_media(candidate) if candidate else None,
            "tags": [serialize_tag(tag) for tag in Tag.query.order_by(Tag.name.asc()).all()],
        }
    )


@bp.get("/duplicates")
@auth_required()
def duplicates():
    rows = (
        _query()
        .with_entities(MediaItem.sha256_hash, func.count(MediaItem.id))
        .group_by(MediaItem.sha256_hash)
        .having(func.count(MediaItem.id) > 1)
        .order_by(func.count(MediaItem.id).desc())
        .limit(100)
        .all()
    )
    groups = []
    for hash_value, count in rows:
        items = _query().filter_by(sha256_hash=hash_value).order_by(MediaItem.created_at.asc()).all()
        groups.append(
            {
                "sha256Hash": hash_value,
                "count": count,
                "items": [serialize_media(item) for item in items],
            }
        )
    return jsonify({"items": groups})


@bp.post("/duplicates/<string:hash_value>/resolve")
@auth_required()
def resolve_duplicates(hash_value: str):
    payload = request.get_json(force=True) or {}
    delete_ids = {int(raw) for raw in payload.get("deleteIds", [])}
    items = _query().filter_by(sha256_hash=hash_value).all()
    removed = 0
    for item in items:
        if item.id in delete_ids:
            _delete_media_item(item)
            removed += 1
    return jsonify({"removed": removed})


@bp.get("/<int:media_id>")
@auth_required()
def get_media(media_id: int):
    return jsonify({"item": serialize_media(_get_accessible(media_id))})


@bp.patch("/<int:media_id>")
@auth_required()
def update_media(media_id: int):
    item = _get_accessible(media_id)
    payload = request.get_json(force=True) or {}
    if "note" in payload:
        item.note = payload["note"]
    if "tagIds" in payload:
        tag_ids = [int(tag_id) for tag_id in payload.get("tagIds", [])]
        item.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all() if tag_ids else []
    db.session.commit()
    return jsonify({"item": serialize_media(item)})


@bp.delete("/<int:media_id>")
@auth_required()
def delete_media(media_id: int):
    item = _get_accessible(media_id)
    _delete_media_item(item)
    return jsonify({"ok": True})


@bp.get("/<int:media_id>/file")
@auth_required()
def stream_media(media_id: int):
    item = _get_accessible(media_id)
    canonical = item.canonical_root
    download_name = item.original_filename if request.args.get("download") == "1" else None
    return build_streaming_response(
        canonical.storage_path,
        canonical.is_encrypted,
        canonical.mime_type,
        download_name=download_name,
    )


@bp.get("/<int:media_id>/preview")
@auth_required()
def stream_preview(media_id: int):
    item = _get_accessible(media_id)
    canonical = item.canonical_root
    if canonical.preview_path:
        return build_streaming_response(
            canonical.preview_path,
            canonical.is_encrypted,
            "image/jpeg",
        )
    return build_streaming_response(
        canonical.storage_path,
        canonical.is_encrypted,
        canonical.mime_type,
    )
