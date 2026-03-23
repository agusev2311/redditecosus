from __future__ import annotations

import threading
import time
from datetime import datetime

from ..extensions import db
from ..models import AlertState
from .export_import import process_export_job
from .importer import process_batch
from .metrics import evaluate_disk_alert
from .telegram import maybe_send_disk_alert


def launch_batch_job(app, batch_id: str) -> None:
    threading.Thread(target=_run_batch, args=(app, batch_id), daemon=True).start()


def _run_batch(app, batch_id: str) -> None:
    with app.app_context():
        process_batch(batch_id)


def launch_export_job(app, job_id: str, push_to_telegram: bool) -> None:
    threading.Thread(
        target=_run_export,
        args=(app, job_id, push_to_telegram),
        daemon=True,
    ).start()


def _run_export(app, job_id: str, push_to_telegram: bool) -> None:
    with app.app_context():
        process_export_job(job_id, push_to_telegram=push_to_telegram)


def start_background_services(app) -> None:
    if app.extensions.get("mediahub_background_services_started"):
        return
    app.extensions["mediahub_background_services_started"] = True
    threading.Thread(target=_monitor_loop, args=(app,), daemon=True).start()


def _monitor_loop(app) -> None:
    while True:
        with app.app_context():
            alert = evaluate_disk_alert()
            state = AlertState.query.filter_by(key="disk.low").first()
            if not state:
                state = AlertState(key="disk.low")
                db.session.add(state)
            if alert["active"] and not state.is_active:
                maybe_send_disk_alert(alert["message"])
                state.last_sent_at = datetime.utcnow()
                state.last_message = alert["message"]
            state.is_active = alert["active"]
            db.session.commit()
        time.sleep(app.config["MONITOR_POLL_SECONDS"])
