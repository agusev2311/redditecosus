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
from ..services.storage import save_uploaded_stream
from ..services.upload_runtime import (
    finalize_upload,
    get_runtime_state,
    sync_batch_model,
    sync_upload_model,
    upload_chunk,
)
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


def _serialize_upload_file(file: UploadFile, state: dict | None = None, include_received_chunks: bool = False):
    payload = {
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
    if include_received_chunks:
        payload["receivedChunkIndexes"] = (state or {}).get("receivedChunkIndexes", [])
    return payload


def _resolve_temp_path(batch: UploadBatch, client_file_id: str, original_filename: str) -> Path:
    safe_prefix = hashlib.sha1(client_file_id.encode("utf-8")).hexdigest()[:24]
    safe_name = slugify(Path(original_filename).stem)[:48]
    suffix = Path(original_filename).suffix
    return Path(batch.temp_dir) / f"{safe_prefix}-{safe_name}{suffix}"


def _sync_batch(batch: UploadBatch) -> list[UploadFile]:
    files = UploadFile.query.filter_by(batch_id=batch.id).all()
    sync_batch_model(batch, files)
    return files


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
    _sync_batch(batch)
    db.session.commit()
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
    batch.uploaded_bytes = (batch.uploaded_bytes or 0) + size
    batch.uploaded_files = (batch.uploaded_files or 0) + 1
    db.session.commit()
    return jsonify({"item": _serialize_upload_file(upload)})


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
            chunk_size=max(chunk_size, 1),
            total_chunks=max(total_chunks, 1),
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
        upload.chunk_size = max(chunk_size or upload.chunk_size or 0, 1)
        upload.total_chunks = max(total_chunks or upload.total_chunks or 0, 1)

    state = get_runtime_state(upload, include_received_chunks=True)
    sync_upload_model(upload, state)
    _sync_batch(batch)
    db.session.commit()
    return jsonify(
        {
            "item": _serialize_upload_file(upload, state=state, include_received_chunks=True),
            "batch": serialize_batch(batch, include_files=False),
        }
    )


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
    chunk_payload = request.get_data(cache=False, as_text=False)
    if not chunk_payload:
        return jsonify({"error": "Missing chunk payload"}), 400

    expected_start_byte = chunk_index * max(upload.chunk_size, 1)
    if start_byte != expected_start_byte:
        state = get_runtime_state(upload, include_received_chunks=True)
        sync_upload_model(upload, state)
        return (
            jsonify(
                {
                    "error": "Chunk offset mismatch",
                    "item": _serialize_upload_file(upload, state=state, include_received_chunks=True),
                    "expectedStartByte": expected_start_byte,
                }
            ),
            409,
        )

    try:
        state, accepted = upload_chunk(upload, chunk_index, start_byte, chunk_payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except RuntimeError:
        state = get_runtime_state(upload, include_received_chunks=True)
        sync_upload_model(upload, state)
        return (
            jsonify(
                {
                    "error": "Chunk offset mismatch",
                    "item": _serialize_upload_file(upload, state=state, include_received_chunks=True),
                    "expectedStartByte": expected_start_byte,
                }
            ),
            409,
        )

    sync_upload_model(upload, state)
    if upload.uploaded_bytes >= upload.size_bytes:
        db.session.commit()

    return jsonify(
        {
            "item": _serialize_upload_file(upload),
            "accepted": accepted,
        }
    )


@bp.post("/<string:batch_id>/files/<string:file_id>/finalize")
@auth_required()
def finalize_upload_file(batch_id: str, file_id: str):
    batch = _batch_scope().filter_by(id=batch_id).first_or_404()
    upload = UploadFile.query.filter_by(batch_id=batch.id, id=file_id).first_or_404()
    state = finalize_upload(upload)
    if int(state["uploadedBytes"]) < int(state["sizeBytes"]) or int(state["uploadedChunks"]) < int(state["totalChunks"]):
        return jsonify({"error": "File is not fully uploaded"}), 400
    sync_upload_model(upload, state)
    upload.status = "uploaded"
    if not upload.finalized_at:
        upload.finalized_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"item": _serialize_upload_file(upload, state=state, include_received_chunks=True)})


@bp.post("/<string:batch_id>/commit")
@auth_required()
def commit_batch(batch_id: str):
    batch = _batch_scope().filter_by(id=batch_id).first_or_404()
    if batch.status not in {"uploading", "pending"}:
        return jsonify({"error": "Batch is already processing"}), 400
    files = UploadFile.query.filter_by(batch_id=batch.id).all()
    if not files:
        return jsonify({"error": "Batch is empty"}), 400

    sync_batch_model(batch, files)
    incomplete = [file.original_filename for file in files if file.uploaded_bytes < file.size_bytes]
    if incomplete:
        db.session.commit()
        return jsonify({"error": "Some files are not fully uploaded yet", "items": incomplete[:10]}), 409

    batch.status = "queued"
    db.session.commit()
    launch_batch_job(current_app._get_current_object(), batch.id)
    return jsonify({"item": serialize_batch(batch)})
