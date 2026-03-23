from __future__ import annotations

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
        original_filename=Path(incoming.filename).name,
        temp_path=destination.as_posix(),
        mime_type=incoming.mimetype,
        size_bytes=size,
        status="uploaded",
    )
    batch.uploaded_files += 1
    batch.uploaded_bytes += size
    db.session.add(upload)
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


@bp.post("/<string:batch_id>/commit")
@auth_required()
def commit_batch(batch_id: str):
    batch = _batch_scope().filter_by(id=batch_id).first_or_404()
    if batch.status not in {"uploading", "pending"}:
        return jsonify({"error": "Batch is already processing"}), 400
    batch.status = "queued"
    db.session.commit()
    launch_batch_job(current_app._get_current_object(), batch.id)
    return jsonify({"item": serialize_batch(batch)})
