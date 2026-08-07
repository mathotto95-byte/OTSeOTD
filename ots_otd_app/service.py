from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

import pandas as pd

from ots_otd_app.time_utils import now_iso


REQUIRED_FIELDS = {
    "previsao_carga": "Previsao Carga",
    "data_limite": "Data Limite",
    "agendamento_carga": "Agendamento Carga",
    "codigo_monitoramento": "Codigo de Monitoramento",
}

EDITABLE_FIELDS = [
    "previsao_carga",
    "data_limite",
    "agendamento_carga",
    "agenda_gfl",
    "codigo_monitoramento",
]


def normalize_spaces(value: object) -> str:
    text = str(value or "").strip()
    return re.sub(r"\s+", " ", text)


def normalizar_codigo_monitoramento(valor: object) -> str:
    return normalize_spaces(valor).upper()


def normalizar_texto(valor: object) -> str:
    return normalize_spaces(valor)


def normalizar_data(valor: object) -> str:
    if valor in [None, ""]:
        return ""
    if isinstance(valor, pd.Timestamp):
        if pd.isna(valor):
            return ""
        return valor.date().isoformat()
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    text = normalizar_texto(valor)
    iso_match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:\s+.*)?", text)
    if iso_match:
        year, month, day = iso_match.groups()
        return f"{year}-{month}-{day}"
    parsed = pd.to_datetime(valor, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return text
    return parsed.date().isoformat()


def montar_payload(
    previsao_carga: object,
    data_limite: object,
    agendamento_carga: object,
    agenda_gfl: object,
    codigo_monitoramento: object,
) -> dict[str, str]:
    return {
        "previsao_carga": normalizar_data(previsao_carga),
        "data_limite": normalizar_data(data_limite),
        "agendamento_carga": normalizar_texto(agendamento_carga),
        "agenda_gfl": normalizar_texto(agenda_gfl),
        "codigo_monitoramento": normalizar_codigo_monitoramento(codigo_monitoramento),
    }


def validar_campos_obrigatorios(dados: dict[str, Any]) -> list[str]:
    missing = []
    for field, label in REQUIRED_FIELDS.items():
        value = dados.get(field)
        if value is None or str(value).strip() == "":
            missing.append(label)
    return missing


def comparar_alteracoes(registro_anterior: dict[str, Any], novos_dados: dict[str, Any]) -> dict[str, dict[str, str]]:
    changes: dict[str, dict[str, str]] = {}
    for field in EDITABLE_FIELDS:
        previous = "" if registro_anterior.get(field) is None else str(registro_anterior.get(field))
        new_value = "" if novos_dados.get(field) is None else str(novos_dados.get(field))
        if previous != new_value:
            changes[field] = {"anterior": previous, "novo": new_value}
    return changes


def dados_alterados_json(changes: dict[str, dict[str, str]]) -> str:
    return json.dumps(changes, ensure_ascii=False, default=str)

