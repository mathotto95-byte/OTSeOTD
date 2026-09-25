"""Backup diario enquanto o processo Streamlit estiver ativo, com recuperacao de atraso."""
import logging
import threading
from urllib.error import HTTPError
import json

from ots_otd_app.github_backup import (
    _download_text, backup_to_github, github_auto_backup_enabled, github_settings,
)
from ots_otd_app.time_utils import now

_START_LOCK = threading.Lock()
_THREAD = None


def backup_due(current, last_date):
    return current.hour >= 1 and last_date != current.date().isoformat()


def _run():
    last_date = None
    while True:
        delay = 30
        try:
            if github_auto_backup_enabled():
                if last_date is None:
                    settings = github_settings()
                    try:
                        last_date = json.loads(_download_text(settings, settings["latest_path"])).get("daily_backup_date", "")
                    except HTTPError as exc:
                        if exc.code != 404:
                            raise
                        last_date = ""
                current = now()
                if backup_due(current, last_date):
                    result = backup_to_github("diario")
                    if result["status"] == "SUCESSO":
                        last_date = current.date().isoformat()
                    else:
                        logging.warning("Backup diario: %s", result["message"])
                        delay = 300
        except Exception:
            logging.exception("Falha no backup diario; nova tentativa em 5 minutos")
            delay = 300
        threading.Event().wait(delay)


def start_daily_backup():
    global _THREAD
    with _START_LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(target=_run, name="ots-backup-diario", daemon=True)
            _THREAD.start()
