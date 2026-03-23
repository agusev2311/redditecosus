from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request

from ..auth import auth_required, get_current_user
from ..extensions import db
from ..models import UploadBatch, UploadFile
from ..services.jobs import launch_batch_job
from ..services.metrics import evaluate_disk_alert
from ..services.serializers import serialize_batch
from ..services.storage import append_upload_chunk, save_uploaded_stream
from ..utils import slugify

bp = Blueprint("uploads", __name__)


def _batch_scope():
    user = get_current_user()
    query = UploadBatch.query
    if not user.is_admin:
        query = query.filter_by(owner_id=user.id)
    return query


def _ensure_upload_allowed():
    user = get_current_user()
    alert = evaluate_disk_alert()
    if alert["uploadsBlockedForUsers"] and not user.is_admin:
        return jsonify({"error": alert["message"], "alert": alert}), 507
    return None


def _refresh_batch_upload_counters(batch: UploadBatch) -> None:
    files = UploadFile.query.filter_by(batch_id=batch.id).all()
    batch.uploaded_files = sum(
        1 for file in files if file.size_bytes > 0 and file.uploaded_bytes >= file.size_bytes
    )
    batch.uploaded_bytes = sum(file.uploaded_bytes for file in files)


def _serialize_upload_file(file: UploadFile):
    return {
        "id": file.id,
        "clientFileId": file.client_file_id,
        "originalFilename": file.original_filename,
        "sizeBytes": file.size_bytes,
        "uploadedBytes": file.uploaded_bytes,
        "chunkSize": file.chunk_size,
        "totalChunks": file.total_chunks,
        "uploadedChunks": file.uploaded_chunks,
        "mimeType": file.mime_type,
        "status": file.status,
        "uploadSource": file.upload_source,
        "finalizedAt": file.finalized_at.isoformat() + "Z" if file.finalized_at else None,
    }


def _resolve_temp_path(batch: UploadBatch, client_file_id: str, original_filename: str) -> Path:
    safe_prefix = hashlib.sha1(client_file_id.encode("utf-8")).hexdigest()[:24]
    safe_name = slugify(Path(original_filename).stem)[:48]
    suffix = Path(original_filename).suffix
    return Path(batch.temp_dir) / f"{safe_prefix}-{safe_name}{suffix}"


@bp.get("")
@auth_required()
def list_batches():
    batches = _batch_scope().order_by(UploadBatch.created_at.desc()).limit(20).all()
    return jsonify({"items": [serialize_batch(batch, include_files=False) for batch in batches]})


@bp.post("")
@auth_required()
def create_batch():
    denied = _ensure_upload_allowed()
    if denied:
        return denied
    payload = request.get_json(force=True) or {}
    batch = UploadBatch(
        owner_id=get_current_user().id,
        client_total_files=int(payload.get("clientTotalFiles") or 0),
        total_bytes=int(payload.get("totalBytes") or 0),
        status="uploading",
        temp_dir=(Path(current_app.config["IMPORTS_ROOT"]) / str(uuid4())).as_posix(),
    )
    Path(batch.temp_dir).mkdir(parents=True, exist_ok=True)
    db.session.add(batch)
    db.session.commit()
    return jsonify({"item": serialize_batch(batch)}), 201


@bp.get("/<string:batch_id>")
@auth_required()
def get_batch(batch_id: str):
    batch = _batch_scope().filter_by(id=batch_id).first_or_404()
    return jsonify({"item": serialize_batch(batch)})


@bp.post("/<string:batch_id>/files")
@auth_required()
def upload_file(batch_id: str):
    denied = _ensure_upload_allowed()
    if denied:
        return denied
    batch = _batch_scope().filter_by(id=batch_id).first_or_404()
    if batch.status not in {"uploading", "pending"}:
        return jsonify({"error": "Batch no longer accepts uploads"}), 400
    incoming = request.files.get("file")
    if not incoming:
        return jsonify({"error": "Missing file"}), 400
    item_id = str(uuid4())
    destination = Path(batch.temp_dir) / f"{item_id}-{Path(incoming.filename).name}"
    size = save_uploaded_stream(incoming, destination)
    upload = UploadFile(
        id=item_id,
        batch_id=batch.id,
        client_file_id=item_id,
        original_filename=Path(incoming.filename).name,
        temp_path=destination.as_posix(),
        mime_type=incoming.mimetype,
        size_bytes=size,
        chunk_size=size,
        total_chunks=1,
        uploaded_chunks=1,
        uploaded_bytes=size,
        upload_source="web",
        finalized_at=datetime.utcnow(),
        status="uploaded",
    )
    db.session.add(upload)
    _refresh_batch_upload_counters(batch)
    db.session.commit()
    return jsonify(
        {
            "item": {
                "id": upload.id,
                "originalFilename": upload.original_filename,
                "sizeBytes": upload.size_bytes,
                "mimeType": upload.mime_type,
                "status": upload.status,
            }
        }
    )


@bp.post("/<string:batch_id>/files/sync")
@auth_required()
def sync_upload_file(batch_id: str):
    denied = _ensure_upload_allowed()
    if denied:
        return denied
    batch = _batch_scope().filter_by(id=batch_id).first_or_404()
    if batch.status not in {"uploading", "pending"}:
        return jsonify({"error": "Batch no longer accepts uploads"}), 400

    payload = request.get_json(force=True) or {}
    client_file_id = (payload.get("clientFileId") or "").strip()
    original_filename = Path(payload.get("originalFilename") or "").name
    size_bytes = int(payload.get("sizeBytes") or 0)
    chunk_size = int(payload.get("chunkSize") or 0)
    total_chunks = int(payload.get("totalChunks") or 0)
    if not client_file_id or not original_filename or size_bytes <= 0:
        return jsonify({"error": "Missing upload file metadata"}), 400

    upload = UploadFile.query.filter_by(batch_id=batch.id, client_file_id=client_file_id).first()
    if not upload:
        temp_path = _resolve_temp_path(batch, client_file_id, original_filename)
        upload = UploadFile(
            batch_id=batch.id,
            client_file_id=client_file_id,
            original_filename=original_filename,
            temp_path=temp_path.as_posix(),
            mime_type=payload.get("mimeType"),
            size_bytes=size_bytes,
            chunk_size=chunk_size,
            total_chunks=total_chunks,
            uploaded_bytes=0,
            uploaded_chunks=0,
            status="uploading",
            upload_source="web",
        )
        db.session.add(upload)
        db.session.flush()
    else:
        upload.original_filename = original_filename or upload.original_filename
        upload.mime_type = payload.get("mimeType") or upload.mime_type
        upload.size_bytes = size_bytes or upload.size_bytes
        upload.chunk_size = chunk_size or upload.chunk_size
        upload.total_chunks = total_chunks or upload.total_chunks

    temp_path = Path(upload.temp_path)
    actual_size = temp_path.stat().st_size if temp_path.exists() else 0
    if actual_size != upload.uploaded_bytes:
        upload.uploaded_bytes = actual_size
    if upload.chunk_size > 0 and upload.uploaded_bytes > 0:
        upload.uploaded_chunks = min(
            upload.total_chunks or upload.uploaded_chunks,
            (upload.uploaded_bytes + upload.chunk_size - 1) // upload.chunk_size,
        )
    upload.status = "uploaded" if upload.uploaded_bytes >= upload.size_bytes else "uploading"
    if upload.status == "uploaded" and not upload.finalized_at:
        upload.finalized_at = datetime.utcnow()

    _refresh_batch_upload_counters(batch)
    db.session.commit()
    return jsonify({"item": _serialize_upload_file(upload), "batch": serialize_batch(batch, include_files=False)})


@bp.put("/<string:batch_id>/files/<string:file_id>/chunk")
@auth_required()
def upload_file_chunk(batch_id: str, file_id: str):
    denied = _ensure_upload_allowed()
    if denied:
        return denied
    batch = _batch_scope().filter_by(id=batch_id).first_or_404()
    upload = UploadFile.query.filter_by(batch_id=batch.id, id=file_id).first_or_404()
    if upload.status not in {"uploading", "uploaded"}:
        return jsonify({"error": "File no longer accepts chunks"}), 400

    start_byte = int(request.headers.get("X-Start-Byte", "0"))
    chunk_index = int(request.headers.get("X-Chunk-Index", "0"))
    payload = request.get_data(cache=False, as_text=False)
    if not payload:
        return jsonify({"error": "Missing chunk payload"}), 400

    actual_start, actual_end = append_upload_chunk(Path(upload.temp_path), start_byte, payload)
    if actual_start != start_byte:
        upload.uploaded_bytes = actual_start
        if upload.chunk_size > 0:
            upload.uploaded_chunks = min(
                upload.total_chunks or upload.uploaded_chunks,
                (upload.uploaded_bytes + upload.chunk_size - 1) // upload.chunk_size,
            )
        _refresh_batch_upload_counters(batch)
        db.session.commit()
        return (
            jsonify(
                {
                    "error": "Chunk offset mismatch",
                    "item": _serialize_upload_file(upload),
                    "expectedStartByte": actual_start,
                }
            ),
            409,
        )

    upload.uploaded_bytes = actual_end
    upload.uploaded_chunks = max(upload.uploaded_chunks, chunk_index + 1)
    upload.status = "uploaded" if upload.uploaded_bytes >= upload.size_bytes else "uploading"
    if upload.status == "uploaded":
        upload.finalized_at = datetime.utcnow()
    _refresh_batch_upload_counters(batch)
    db.session.commit()
    return jsonify({"item": _serialize_upload_file(upload), "batch": serialize_batch(batch, include_files=False)})


@bp.post("/<string:batch_id>/files/<string:file_id>/finalize")
@auth_required()
def finalize_upload_file(batch_id: str, file_id: str):
    batch = _batch_scope().filter_by(id=batch_id).first_or_404()
    upload = UploadFile.query.filter_by(batch_id=batch.id, id=file_id).first_or_404()
    if upload.uploaded_bytes < upload.size_bytes:
        return jsonify({"error": "File is not fully uploaded"}), 400
    upload.status = "uploaded"
    if not upload.finalized_at:
        upload.finalized_at = datetime.utcnow()
    _refresh_batch_upload_counters(batch)
    db.session.commit()
    return jsonify({"item": _serialize_upload_file(upload), "batch": serialize_batch(batch, include_files=False)})


@bp.post("/<string:batch_id>/commit")
@auth_required()
def commit_batch(batch_id: str):
    batch = _batch_scope().filter_by(id=batch_id).first_or_404()
    if batch.status not in {"uploading", "pending"}:
        return jsonify({"error": "Batch is already processing"}), 400
    files = UploadFile.query.filter_by(batch_id=batch.id).all()
    if not files:
        return jsonify({"error": "Batch is empty"}), 400
    incomplete = [file.original_filename for file in files if file.uploaded_bytes < file.size_bytes]
    if incomplete:
        return jsonify({"error": "Some files are not fully uploaded yet", "items": incomplete[:10]}), 409
    batch.status = "queued"
    _refresh_batch_upload_counters(batch)
    db.session.commit()
    launch_batch_job(current_app._get_current_object(), batch.id)
    return jsonify({"item": serialize_batch(batch)})
