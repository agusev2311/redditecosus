from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..extensions import db
from ..models import User
from ..services.settings import set_setting

bp = Blueprint("setup", __name__)


@bp.get("/status")
def status():
    configured = User.query.count() > 0
    return jsonify({"configured": configured, "needsSetup": not configured})


@bp.post("/bootstrap")
def bootstrap():
    if User.query.count() > 0:
        return jsonify({"error": "Application has already been configured"}), 400

    payload = request.get_json(force=True) or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    display_name = (payload.get("displayName") or username).strip()
    if len(username) < 3 or len(password) < 8:
        return jsonify({"error": "Username or password is too short"}), 400

    user = User(username=username, display_name=display_name, role="admin", is_active=True)
    user.set_password(password)
    db.session.add(user)

    if "warningGb" in payload:
        set_setting("storage.warning_gb", payload.get("warningGb"))
    if "warningPercent" in payload:
        set_setting("storage.warning_percent", payload.get("warningPercent"))
    if "telegramBotToken" in payload:
        set_setting("telegram.bot_token", payload.get("telegramBotToken"))
    if "telegramChatId" in payload:
        set_setting("telegram.chat_id", payload.get("telegramChatId"))
    if "telegramAutoDiskAlerts" in payload:
        set_setting("telegram.auto_disk_alerts", payload.get("telegramAutoDiskAlerts"))
    if "telegramAutoBackupEnabled" in payload:
        set_setting("telegram.auto_backup_enabled", payload.get("telegramAutoBackupEnabled"))

    db.session.commit()
    return jsonify({"ok": True})
