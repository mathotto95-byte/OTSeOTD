from __future__ import annotations

import re
from typing import Any

import pandas as pd

from ots_otd_app.repository import salvar_payload_com_historico
from ots_otd_app.service import montar_payload, validar_campos_obrigatorios


COLUMN_ALIASES = {
    "previsao_carga": [
        "previsao carga",
        "previsão carga",
        "previsao de carga",
        "previsão de carga",
        "data previsao carga",
    ],
    "data_limite": ["data limite", "limite", "deadline"],
    "agendamento_carga": ["agendamento carga", "agendamento de carga", "agenda carga", "carga"],
    "agenda_gfl": ["agenda gfl", "gfl"],
    "codigo_monitoramento": [
        "codigo monitoramento",
        "código monitoramento",
        "codigo de monitoramento",
        "código de monitoramento",
        "codigo",
        "código",
    ],
}


def _norm_column(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[_\-.]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def map_columns(df: pd.DataFrame) -> dict[str, str]:
    normalized = {_norm_column(column): str(column) for column in df.columns}
    mapped: dict[str, str] = {}
    for target, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapped[target] = normalized[alias]
                break
    return mapped


def import_excel(file, usuario: str) -> dict[str, Any]:
    df = pd.read_excel(file)
    mapped = map_columns(df)
    missing_columns = [field for field in ["previsao_carga", "data_limite", "agendamento_carga", "codigo_monitoramento"] if field not in mapped]
    if missing_columns:
        labels = {
            "previsao_carga": "Previsao Carga",
            "data_limite": "Data Limite",
            "agendamento_carga": "Agendamento Carga",
            "codigo_monitoramento": "Codigo de Monitoramento",
        }
        return {
            "status": "ERRO_LAYOUT",
            "message": "Colunas obrigatorias nao encontradas: " + ", ".join(labels[field] for field in missing_columns),
            "rows": [],
            "summary": {"lidas": int(len(df)), "incluidas": 0, "alteradas": 0, "ignoradas": 0, "erros": 0},
            "mapped": mapped,
        }

    rows: list[dict[str, Any]] = []
    summary = {"lidas": int(len(df)), "incluidas": 0, "alteradas": 0, "ignoradas": 0, "erros": 0}
    for index, row in df.iterrows():
        payload = montar_payload(
            row.get(mapped["previsao_carga"]),
            row.get(mapped["data_limite"]),
            row.get(mapped["agendamento_carga"]),
            row.get(mapped.get("agenda_gfl", "")),
            row.get(mapped["codigo_monitoramento"]),
        )
        missing = validar_campos_obrigatorios(payload)
        if missing:
            summary["erros"] += 1
            rows.append({"linha": int(index) + 2, "status": "ERRO", "codigo": payload.get("codigo_monitoramento"), "mensagem": "Campos pendentes: " + ", ".join(missing)})
            continue
        try:
            action, new_id, message = salvar_payload_com_historico(payload, usuario)
            if action == "incluido":
                summary["incluidas"] += 1
                status = "INCLUIDO"
            elif action == "alterado":
                summary["alteradas"] += 1
                status = "ALTERADO"
            else:
                summary["ignoradas"] += 1
                status = "IGNORADO"
            rows.append({"linha": int(index) + 2, "status": status, "codigo": payload["codigo_monitoramento"], "id": new_id or "", "mensagem": message})
        except Exception as exc:
            summary["erros"] += 1
            rows.append({"linha": int(index) + 2, "status": "ERRO", "codigo": payload.get("codigo_monitoramento"), "mensagem": str(exc)})
    return {"status": "SUCESSO" if not summary["erros"] else "PARCIAL", "message": "", "rows": rows, "summary": summary, "mapped": mapped}

