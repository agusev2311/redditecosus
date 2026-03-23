from __future__ import annotations

from datetime import datetime

from flask import current_app, has_request_context, request, url_for

from ..auth import extract_request_token

from ..models import UploadFile
from .tag_media import resolve_avatar_reference
from .tag_styles import decode_gradient_colors


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


def _url_with_token(endpoint: str, **values) -> str:
    url = url_for(endpoint, **values)
    token = extract_request_token()
    if not token:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}token={token}"


def _configured_frontend_base_url() -> str:
    return current_app.config["FRONTEND_BASE_URL"].rstrip("/")


def _is_local_frontend_url(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in ("localhost", "127.0.0.1", "0.0.0.0", "[::1]"))


def _request_frontend_base_url() -> str | None:
    if not has_request_context():
        return None
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme).strip()
    host = (
        request.headers.get("X-Forwarded-Host")
        or request.headers.get("Host")
        or request.host
        or ""
    ).strip()
    if not host:
        return None
    return f"{scheme}://{host}".rstrip("/")


def _frontend_base_url() -> str:
    configured = _configured_frontend_base_url()
    request_url = _request_frontend_base_url()
    if configured and not _is_local_frontend_url(configured):
        return configured
    if request_url:
        return request_url
    return configured


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
    avatar_url, avatar_source_type, avatar_media_id = resolve_avatar_reference(tag.avatar_url, _url_with_token)
    return {
        "id": tag.id,
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
        "gradientAngle": tag.gradient_angle or 135,
        "textColor": tag.text_color,
        "avatarUrl": avatar_url,
        "avatarSourceValue": tag.avatar_url,
        "avatarSourceType": avatar_source_type,
        "avatarMediaId": avatar_media_id,
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
        "perceptualHash": item.perceptual_hash,
        "note": item.note,
        "isDuplicate": item.is_duplicate,
        "canonicalMediaId": canonical.id if canonical else item.id,
        "isEncrypted": item.is_encrypted,
        "createdAt": _iso(item.created_at),
        "updatedAt": _iso(item.updated_at),
        "tags": [serialize_tag(tag) for tag in item.tags],
        "fileUrl": _url_with_token("media.stream_media", media_id=item.id),
        "previewUrl": _url_with_token("media.stream_preview", media_id=item.id),
        "downloadUrl": _url_with_token("media.stream_media", media_id=item.id, download=1),
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
                "chunkSize": file.chunk_size,
                "totalChunks": file.total_chunks,
                "uploadedChunks": file.uploaded_chunks,
                "uploadedBytes": file.uploaded_bytes,
                "mimeType": file.mime_type,
                "clientFileId": file.client_file_id,
                "uploadSource": file.upload_source,
                "status": file.status,
                "errorMessage": file.error_message,
                "finalizedAt": _iso(file.finalized_at),
                "createdAt": _iso(file.created_at),
            }
            for file in files
        ]
    return payload


def serialize_share(share):
    frontend = _frontend_base_url()
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
