from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file

from ..auth import auth_required, get_current_user
from ..extensions import db
from ..models import ExportJob
from ..services.export_import import import_export_archive
from ..services.jobs import launch_export_job
from ..services.metrics import get_metrics_snapshot
from ..services.serializers import serialize_export_job
from ..services.settings import get_bool_setting, get_setting, set_setting
from ..services.telegram import send_message
from ..services.storage import save_uploaded_stream

bp = Blueprint("admin", __name__)


@bp.get("/metrics")
@auth_required(admin=True)
def metrics():
    return jsonify(get_metrics_snapshot())


@bp.get("/settings")
@auth_required(admin=True)
def settings():
    return jsonify(
        {
            "warningGb": int(get_setting("storage.warning_gb") or current_app.config["LOW_DISK_THRESHOLD_GB"]),
            "warningPercent": int(
                get_setting("storage.warning_percent") or current_app.config["LOW_DISK_THRESHOLD_PERCENT"]
            ),
            "telegramBotTokenMasked": (
                f"***{str(get_setting('telegram.bot_token'))[-4:]}"
                if get_setting("telegram.bot_token")
                else ""
            ),
            "telegramChatId": get_setting("telegram.chat_id") or "",
            "telegramAutoBackupEnabled": get_bool_setting("telegram.auto_backup_enabled", False),
            "telegramAutoDiskAlerts": get_bool_setting("telegram.auto_disk_alerts", True),
            "encryptionEnabled": bool(current_app.config["MEDIA_ENCRYPTION_PASSPHRASE"]),
        }
    )


@bp.put("/settings")
@auth_required(admin=True)
def update_settings():
    payload = request.get_json(force=True) or {}
    if "warningGb" in payload:
        set_setting("storage.warning_gb", payload["warningGb"])
    if "warningPercent" in payload:
        set_setting("storage.warning_percent", payload["warningPercent"])
    if "telegramBotToken" in payload:
        set_setting("telegram.bot_token", payload["telegramBotToken"])
    if "telegramChatId" in payload:
        set_setting("telegram.chat_id", payload["telegramChatId"])
    if "telegramAutoBackupEnabled" in payload:
        set_setting("telegram.auto_backup_enabled", payload["telegramAutoBackupEnabled"])
    if "telegramAutoDiskAlerts" in payload:
        set_setting("telegram.auto_disk_alerts", payload["telegramAutoDiskAlerts"])
    db.session.commit()
    return jsonify({"ok": True})


@bp.post("/telegram/test")
@auth_required(admin=True)
def telegram_test():
    try:
        send_message("MediaHub test message: Telegram integration is working.")
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True})


@bp.get("/exports")
@auth_required(admin=True)
def list_exports():
    jobs = ExportJob.query.order_by(ExportJob.created_at.desc()).all()
    return jsonify({"items": [serialize_export_job(job) for job in jobs]})


@bp.post("/exports")
@auth_required(admin=True)
def create_export():
    payload = request.get_json(force=True) or {}
    push_to_telegram = bool(payload.get("pushToTelegram"))
    job = ExportJob(created_by_id=get_current_user().id, status="queued")
    db.session.add(job)
    db.session.commit()
    launch_export_job(current_app._get_current_object(), job.id, push_to_telegram=push_to_telegram)
    return jsonify({"item": serialize_export_job(job)}), 202


@bp.get("/exports/<string:job_id>/download")
@auth_required(admin=True)
def download_export(job_id: str):
    job = ExportJob.query.get_or_404(job_id)
    if not job.archive_path:
        return jsonify({"error": "Archive is not ready"}), 404
    return send_file(job.archive_path, as_attachment=True, download_name=Path(job.archive_path).name)


@bp.post("/imports")
@auth_required(admin=True)
def import_archive():
    incoming = request.files.get("file")
    if not incoming:
        return jsonify({"error": "Missing file"}), 400
    destination = Path(current_app.config["IMPORTS_ROOT"]) / f"import-{Path(incoming.filename).name}"
    save_uploaded_stream(incoming, destination)
    result = import_export_archive(destination)
    return jsonify({"ok": True, "result": result})
