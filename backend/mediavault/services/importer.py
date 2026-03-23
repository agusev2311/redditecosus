from __future__ import annotations

import mimetypes
import shutil
import tarfile
import tempfile
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

from ..extensions import db
from ..models import MediaItem, UploadBatch, UploadFile
from .storage import (
    calculate_sha256,
    generate_image_preview,
    guess_media_type,
    inspect_image_size,
    is_archive_file,
    store_original,
    store_preview,
)


def _batch_file_rows(batch_id: str):
    return UploadFile.query.filter_by(batch_id=batch_id).order_by(UploadFile.created_at.asc()).all()


def _canonical_for_hash(hash_hex: str):
    item = (
        MediaItem.query.filter_by(sha256_hash=hash_hex)
        .order_by(MediaItem.is_duplicate.asc(), MediaItem.created_at.asc())
        .first()
    )
    return item.canonical_root if item else None


def _prepare_media_record(owner_id: int, batch_id: str, original_filename: str, source_path: Path):
    from flask import current_app

    media_type = guess_media_type(original_filename)
    if not media_type:
        raise ValueError(f"Unsupported file type: {original_filename}")

    sha256_hash = calculate_sha256(source_path)
    size_bytes = source_path.stat().st_size
    existing = _canonical_for_hash(sha256_hash)

    if existing:
        item = MediaItem(
            owner_id=owner_id,
            upload_batch_id=batch_id,
            original_filename=original_filename,
            storage_path=existing.storage_path,
            preview_path=existing.preview_path,
            media_type=existing.media_type,
            mime_type=existing.mime_type,
            size_bytes=size_bytes,
            width=existing.width,
            height=existing.height,
            duration_seconds=existing.duration_seconds,
            sha256_hash=sha256_hash,
            is_encrypted=existing.is_encrypted,
            is_duplicate=True,
            canonical_media_id=existing.id,
        )
        return item, True, size_bytes

    mime_type = mimetypes.guess_type(original_filename)[0] or (
        "image/jpeg" if media_type == "image" else "video/mp4"
    )
    width = height = None
    preview_path = None
    if media_type == "image":
        width, height = inspect_image_size(source_path)
        preview_temp = Path(tempfile.mkdtemp(dir=current_app.config["IMPORTS_ROOT"])) / f"{sha256_hash}.jpg"
        width, height = generate_image_preview(source_path, preview_temp)
        preview_path = store_preview(preview_temp, sha256_hash)

    storage_path = store_original(source_path, sha256_hash, original_filename)

    item = MediaItem(
        owner_id=owner_id,
        upload_batch_id=batch_id,
        original_filename=original_filename,
        storage_path=storage_path,
        preview_path=preview_path,
        media_type=media_type,
        mime_type=mime_type,
        size_bytes=size_bytes,
        width=width,
        height=height,
        duration_seconds=None,
        sha256_hash=sha256_hash,
        is_encrypted=bool(current_app.config["MEDIA_ENCRYPTION_PASSPHRASE"]),
        is_duplicate=False,
    )
    return item, False, size_bytes


def _import_single_path(batch: UploadBatch, original_filename: str, source_path: Path) -> None:
    batch.total_items += 1
    try:
        item, duplicate, size_bytes = _prepare_media_record(
            batch.owner_id, batch.id, original_filename, source_path
        )
        db.session.add(item)
        batch.stored_items += 1
        if duplicate:
            batch.duplicate_items += 1
        batch.processed_bytes += size_bytes
    except Exception as exc:
        batch.failed_items += 1
        if not batch.error_message:
            batch.error_message = str(exc)
    finally:
        source_path.unlink(missing_ok=True)
        batch.processed_items += 1
        db.session.commit()


def _import_archive(batch: UploadBatch, upload_file: UploadFile) -> None:
    from flask import current_app

    upload_path = Path(upload_file.temp_path)
    extract_root = Path(current_app.config["IMPORTS_ROOT"]) / f"{upload_file.id}-extract"
    extract_root.mkdir(parents=True, exist_ok=True)

    if upload_file.original_filename.lower().endswith(".zip"):
        with zipfile.ZipFile(upload_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                temp_target = extract_root / Path(member.filename).name
                with archive.open(member) as source, temp_target.open("wb") as target:
                    target.write(source.read())
                if guess_media_type(member.filename):
                    _import_single_path(batch, Path(member.filename).name, temp_target)
    else:
        with tarfile.open(upload_path) as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                temp_target = extract_root / Path(member.name).name
                extracted = archive.extractfile(member)
                if not extracted:
                    continue
                with temp_target.open("wb") as target:
                    target.write(extracted.read())
                if guess_media_type(member.name):
                    _import_single_path(batch, Path(member.name).name, temp_target)
    shutil.rmtree(extract_root, ignore_errors=True)


def process_batch(batch_id: str) -> None:
    batch = UploadBatch.query.get(batch_id)
    if not batch:
        return

    batch.status = "processing"
    batch.started_processing_at = datetime.utcnow()
    batch.error_message = None
    db.session.commit()

    try:
        for upload_file in _batch_file_rows(batch.id):
            upload_file.status = "processing"
            db.session.commit()
            try:
                if is_archive_file(upload_file.original_filename):
                    _import_archive(batch, upload_file)
                else:
                    _import_single_path(batch, upload_file.original_filename, Path(upload_file.temp_path))
                upload_file.status = "completed"
            except Exception:
                upload_file.status = "failed"
                upload_file.error_message = traceback.format_exc(limit=2)
                batch.failed_items += 1
                if not batch.error_message:
                    batch.error_message = upload_file.error_message
            finally:
                db.session.commit()
        batch.status = "completed" if batch.failed_items == 0 else "completed_with_warnings"
    except Exception:
        batch.status = "failed"
        batch.error_message = traceback.format_exc(limit=4)
    finally:
        batch.finished_at = datetime.utcnow()
        db.session.commit()
        shutil.rmtree(batch.temp_dir, ignore_errors=True)
