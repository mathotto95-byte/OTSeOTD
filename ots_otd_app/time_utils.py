from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")


def now() -> datetime:
    return datetime.now(BRASILIA_TZ)


def now_iso() -> str:
    return now().replace(microsecond=0).isoformat()

