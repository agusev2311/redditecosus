from __future__ import annotations

from typing import Any

from ..extensions import db
from ..models import AppSetting


def get_setting(key: str, default: Any = None) -> Any:
    row = AppSetting.query.filter_by(key=key).first()
    return row.value if row else default


def get_int_setting(key: str, default: int) -> int:
    value = get_setting(key)
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def get_bool_setting(key: str, default: bool = False) -> bool:
    value = get_setting(key)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def set_setting(key: str, value: Any) -> AppSetting:
    row = AppSetting.query.filter_by(key=key).first()
    if not row:
        row = AppSetting(key=key)
        db.session.add(row)
    row.value = "" if value is None else str(value)
    return row


def seed_default_settings(app) -> None:
    defaults = {
        "storage.warning_gb": app.config["LOW_DISK_THRESHOLD_GB"],
        "storage.warning_percent": app.config["LOW_DISK_THRESHOLD_PERCENT"],
        "telegram.bot_token": "",
        "telegram.chat_id": "",
        "telegram.auto_backup_enabled": "false",
        "telegram.auto_disk_alerts": "true",
        "telegram.polling_enabled": "true",
        "telegram.last_update_id": "0",
    }
    changed = False
    for key, value in defaults.items():
        if get_setting(key) is None:
            set_setting(key, value)
            changed = True
    if changed:
        db.session.commit()
