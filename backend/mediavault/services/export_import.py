from __future__ import annotations

import json
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from flask import current_app

from ..extensions import db
from ..models import ExportJob, MediaItem, Tag, User
from .settings import get_setting
from .storage import iter_storage_chunks, store_original, store_preview
from .tag_styles import decode_gradient_colors
from .telegram import send_document_chunks


def _export_manifest():
    return {
        "version": 2,
        "exportedAt": datetime.utcnow().isoformat() + "Z",
        "settings": {
            "storage.warning_gb": get_setting("storage.warning_gb"),
            "storage.warning_percent": get_setting("storage.warning_percent"),
        },
        "users": [
            {
                "username": user.username,
                "displayName": user.display_name,
                "role": user.role,
                "isActive": user.is_active,
                "passwordHash": (
                    user.password_hash if current_app.config["EXPORT_INCLUDE_PASSWORD_HASHES"] else None
                ),
                "createdAt": user.created_at.isoformat() + "Z",
            }
            for user in User.query.order_by(User.id.asc()).all()
        ],
        "tags": [
            {
                "name": tag.name,
                "slug": tag.slug,
                "description": tag.description,
                "styleMode": tag.style_mode,
                "colorStart": tag.color_start,
                "colorEnd": tag.color_end,
                "gradientColors": decode_gradient_colors(
                    tag.gradient_colors,
                    fallback_start=tag.color_start,
                    fallback_end=tag.color_end,
                ),
                "gradientAngle": tag.gradient_angle,
                "textColor": tag.text_color,
                "avatarUrl": tag.avatar_url,
            }
            for tag in Tag.query.order_by(Tag.id.asc()).all()
        ],
        "media": [
            {
                "ownerUsername": item.owner.username,
                "originalFilename": item.original_filename,
                "mediaType": item.media_type,
                "mimeType": item.mime_type,
                "sizeBytes": item.size_bytes,
                "width": item.width,
                "height": item.height,
                "durationSeconds": item.duration_seconds,
                "sha256Hash": item.sha256_hash,
                "perceptualHash": item.perceptual_hash,
                "note": item.note,
                "isDuplicate": item.is_duplicate,
                "canonicalHash": item.canonical_root.sha256_hash,
                "storageKey": f"files/{item.canonical_root.sha256_hash}/{Path(item.canonical_root.storage_path).name}",
                "previewKey": (
                    f"previews/{item.canonical_root.sha256_hash}/{Path(item.canonical_root.preview_path).name}"
                    if item.canonical_root.preview_path
                    else None
                ),
                "tags": [tag.slug for tag in item.tags],
                "createdAt": item.created_at.isoformat() + "Z",
            }
            for item in MediaItem.query.order_by(MediaItem.id.asc()).all()
        ],
    }


def process_export_job(job_id: str, push_to_telegram: bool = False) -> None:
    job = ExportJob.query.get(job_id)
    if not job:
        return
    job.status = "processing"
    db.session.commit()

    archive_path = Path(current_app.config["EXPORTS_ROOT"]) / f"mediahub-export-{job.id}.zip"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = _export_manifest()

    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            written = set()
            for item in MediaItem.query.order_by(MediaItem.id.asc()).all():
                canonical = item.canonical_root
                file_key = f"files/{canonical.sha256_hash}/{Path(canonical.storage_path).name}"
                if file_key not in written:
                    with archive.open(file_key, "w") as target:
                        for chunk in iter_storage_chunks(canonical.storage_path, canonical.is_encrypted):
                            target.write(chunk)
                    written.add(file_key)
                if canonical.preview_path:
                    preview_key = f"previews/{canonical.sha256_hash}/{Path(canonical.preview_path).name}"
                    if preview_key not in written:
                        with archive.open(preview_key, "w") as target:
                            for chunk in iter_storage_chunks(canonical.preview_path, canonical.is_encrypted):
                                target.write(chunk)
                        written.add(preview_key)

        job.archive_path = archive_path.as_posix()
        job.size_bytes = archive_path.stat().st_size
        if push_to_telegram:
            send_document_chunks(job.archive_path, caption_prefix=f"MediaHub export {job.id}")
            job.pushed_to_telegram = True
        job.status = "completed"
        job.finished_at = datetime.utcnow()
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
    finally:
        db.session.commit()


def import_export_archive(archive_path: Path) -> dict:
    imported_media = 0
    created_users = 0
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

        users_by_name = {}
        for raw_user in manifest.get("users", []):
            user = User.query.filter_by(username=raw_user["username"]).first()
            if not user:
                user = User(
                    username=raw_user["username"],
                    display_name=raw_user["displayName"],
                    role=raw_user["role"],
                    is_active=raw_user["isActive"],
                    password_hash=raw_user.get("passwordHash") or "",
                )
                db.session.add(user)
                created_users += 1
            users_by_name[raw_user["username"]] = user

        tags_by_slug = {}
        for raw_tag in manifest.get("tags", []):
            tag = Tag.query.filter_by(slug=raw_tag["slug"]).first()
            if not tag:
                tag = Tag(
                    name=raw_tag["name"],
                    slug=raw_tag["slug"],
                    description=raw_tag.get("description"),
                    style_mode=raw_tag.get("styleMode", "gradient"),
                    color_start=raw_tag.get("colorStart", "#7c3aed"),
                    color_end=raw_tag.get("colorEnd", "#10b981"),
                    gradient_colors=(
                        json.dumps(raw_tag.get("gradientColors"), ensure_ascii=False)
                        if raw_tag.get("gradientColors")
                        else None
                    ),
                    gradient_angle=raw_tag.get("gradientAngle", 135),
                    text_color=raw_tag.get("textColor", "#f8fafc"),
                    avatar_url=raw_tag.get("avatarUrl"),
                )
                db.session.add(tag)
            tags_by_slug[tag.slug] = tag
        db.session.commit()

        temp_root = Path(tempfile.mkdtemp(dir=current_app.config["IMPORTS_ROOT"]))
        stored_cache = {}
        for raw_media in manifest.get("media", []):
            owner = users_by_name.get(raw_media["ownerUsername"])
            if not owner:
                continue

            existing = MediaItem.query.filter_by(
                owner_id=owner.id,
                sha256_hash=raw_media["sha256Hash"],
                original_filename=raw_media["originalFilename"],
            ).first()
            if existing:
                continue

            storage_key = raw_media["storageKey"]
            if storage_key not in stored_cache:
                temp_original = temp_root / Path(storage_key).name
                with archive.open(storage_key) as source, temp_original.open("wb") as target:
                    target.write(source.read())
                storage_path = store_original(
                    temp_original,
                    raw_media["canonicalHash"],
                    raw_media["originalFilename"],
                )
                preview_path = None
                if raw_media.get("previewKey"):
                    temp_preview = temp_root / Path(raw_media["previewKey"]).name
                    with archive.open(raw_media["previewKey"]) as source, temp_preview.open("wb") as target:
                        target.write(source.read())
                    preview_path = store_preview(temp_preview, raw_media["canonicalHash"])
                stored_cache[storage_key] = (storage_path, preview_path)

            storage_path, preview_path = stored_cache[storage_key]
            canonical = MediaItem.query.filter_by(sha256_hash=raw_media["canonicalHash"], is_duplicate=False).first()
            item = MediaItem(
                owner_id=owner.id,
                original_filename=raw_media["originalFilename"],
                storage_path=storage_path,
                preview_path=preview_path,
                media_type=raw_media["mediaType"],
                mime_type=raw_media["mimeType"],
                size_bytes=raw_media["sizeBytes"],
                width=raw_media.get("width"),
                height=raw_media.get("height"),
                duration_seconds=raw_media.get("durationSeconds"),
                sha256_hash=raw_media["sha256Hash"],
                perceptual_hash=raw_media.get("perceptualHash"),
                note=raw_media.get("note"),
                is_encrypted=bool(current_app.config["MEDIA_ENCRYPTION_PASSPHRASE"]),
                is_duplicate=raw_media.get("isDuplicate", False),
                canonical_media_id=canonical.id if canonical else None,
            )
            item.tags = [tags_by_slug[slug] for slug in raw_media.get("tags", []) if slug in tags_by_slug]
            db.session.add(item)
            imported_media += 1
        db.session.commit()

    return {"importedMedia": imported_media, "createdUsers": created_users}
