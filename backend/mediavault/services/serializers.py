from __future__ import annotations

from datetime import datetime

from flask import current_app, url_for

from ..models import UploadFile


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


def serialize_user(user):
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "role": user.role,
        "isActive": user.is_active,
        "createdAt": _iso(user.created_at),
    }


def serialize_tag(tag):
    return {
        "id": tag.id,
        "name": tag.name,
        "slug": tag.slug,
        "description": tag.description,
        "styleMode": tag.style_mode,
        "colorStart": tag.color_start,
        "colorEnd": tag.color_end,
        "textColor": tag.text_color,
        "avatarUrl": tag.avatar_url,
        "createdAt": _iso(tag.created_at),
    }


def serialize_media(item):
    canonical = item.canonical_root
    return {
        "id": item.id,
        "ownerId": item.owner_id,
        "ownerName": item.owner.display_name if item.owner else None,
        "originalFilename": item.original_filename,
        "mediaType": item.media_type,
        "mimeType": item.mime_type,
        "sizeBytes": item.size_bytes,
        "width": item.width,
        "height": item.height,
        "durationSeconds": item.duration_seconds,
        "sha256Hash": item.sha256_hash,
        "note": item.note,
        "isDuplicate": item.is_duplicate,
        "canonicalMediaId": canonical.id if canonical else item.id,
        "isEncrypted": item.is_encrypted,
        "createdAt": _iso(item.created_at),
        "updatedAt": _iso(item.updated_at),
        "tags": [serialize_tag(tag) for tag in item.tags],
        "fileUrl": url_for("media.stream_media", media_id=item.id),
        "previewUrl": url_for("media.stream_preview", media_id=item.id),
        "downloadUrl": url_for("media.stream_media", media_id=item.id, download=1),
    }


def serialize_batch(batch, include_files: bool = True):
    payload = {
        "id": batch.id,
        "ownerId": batch.owner_id,
        "clientTotalFiles": batch.client_total_files,
        "uploadedFiles": batch.uploaded_files,
        "totalItems": batch.total_items,
        "processedItems": batch.processed_items,
        "storedItems": batch.stored_items,
        "duplicateItems": batch.duplicate_items,
        "failedItems": batch.failed_items,
        "totalBytes": batch.total_bytes,
        "uploadedBytes": batch.uploaded_bytes,
        "processedBytes": batch.processed_bytes,
        "status": batch.status,
        "errorMessage": batch.error_message,
        "createdAt": _iso(batch.created_at),
        "updatedAt": _iso(batch.updated_at),
        "startedProcessingAt": _iso(batch.started_processing_at),
        "finishedAt": _iso(batch.finished_at),
    }
    if include_files:
        files = (
            UploadFile.query.filter_by(batch_id=batch.id)
            .order_by(UploadFile.created_at.desc())
            .all()
        )
        payload["files"] = [
            {
                "id": file.id,
                "originalFilename": file.original_filename,
                "sizeBytes": file.size_bytes,
                "mimeType": file.mime_type,
                "status": file.status,
                "errorMessage": file.error_message,
                "createdAt": _iso(file.created_at),
            }
            for file in files
        ]
    return payload


def serialize_share(share):
    frontend = current_app.config["FRONTEND_BASE_URL"].rstrip("/")
    return {
        "id": share.id,
        "token": share.token,
        "mediaId": share.media_id,
        "expiresAt": _iso(share.expires_at),
        "maxViews": share.max_views,
        "viewCount": share.view_count,
        "burnAfterRead": share.burn_after_read,
        "isRevoked": share.is_revoked,
        "createdAt": _iso(share.created_at),
        "lastViewedAt": _iso(share.last_viewed_at),
        "shareUrl": f"{frontend}/share/{share.token}",
        "media": serialize_media(share.media) if share.media else None,
    }


def serialize_export_job(job):
    return {
        "id": job.id,
        "status": job.status,
        "archivePath": job.archive_path,
        "sizeBytes": job.size_bytes,
        "pushedToTelegram": job.pushed_to_telegram,
        "errorMessage": job.error_message,
        "createdAt": _iso(job.created_at),
        "updatedAt": _iso(job.updated_at),
        "finishedAt": _iso(job.finished_at),
        "downloadUrl": (
            url_for("admin.download_export", job_id=job.id) if job.archive_path else None
        ),
    }
