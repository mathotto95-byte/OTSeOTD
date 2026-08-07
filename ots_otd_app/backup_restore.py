from __future__ import annotations

import json
from typing import Any

import pandas as pd

from ots_otd_app.database import get_connection, read_sql
from ots_otd_app.github_backup import BACKUP_COLUMNS
from ots_otd_app.time_utils import now_iso


DISPLAY_TO_INTERNAL = {
    "ID": "id",
    "Status": "tipo_registro",
    "Previsao Carga": "previsao_carga",
    "Data Limite": "data_limite",
    "Agendamento Carga": "agendamento_carga",
    "Agenda GFL": "agenda_gfl",
    "Codigo de Monitoramento": "codigo_monitoramento",
    "Data/Hora do Registro": "data_hora_registro",
    "Usuario": "usuario_registro",
    "ID do Registro Anterior": "registro_origem_id",
    "Dados Alterados": "dados_alterados",
}


def all_database_records() -> pd.DataFrame:
    return read_sql(
        """
        select id, previsao_carga, data_limite, agendamento_carga, agenda_gfl,
               codigo_monitoramento, tipo_registro, data_hora_registro,
               usuario_registro, registro_origem_id, dados_alterados, created_at, updated_at
        from ots_otd_registros
        order by id
        """
    )


def backup_payload(df: pd.DataFrame | None = None) -> dict[str, Any]:
    df = all_database_records() if df is None else df
    rows = json.loads(df.where(pd.notna(df), None).to_json(orient="records", force_ascii=False))
    return {
        "schema": "ots_otd_backup_v1",
        "generated_at": now_iso(),
        "records": int(len(rows)),
        "rows": rows,
    }


def backup_json_bytes() -> bytes:
    return json.dumps(backup_payload(), ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = {column: _clean_value(row.get(column)) for column in BACKUP_COLUMNS}
    if normalized.get("dados_alterados") in [None, ""]:
        normalized["dados_alterados"] = "{}"
    for column in ["agenda_gfl", "created_at", "updated_at"]:
        if normalized.get(column) is None:
            normalized[column] = ""
    return normalized


def _parse_json_backup(content: bytes) -> list[dict[str, Any]]:
    payload = json.loads(content.decode("utf-8-sig"))
    if isinstance(payload, list):
        rows = payload
    else:
        if str(payload.get("schema") or "") != "ots_otd_backup_v1":
            raise ValueError("Arquivo JSON nao e um backup OTS/OTD valido.")
        rows = payload.get("rows") or []
    if not isinstance(rows, list):
        raise ValueError("Backup JSON sem lista de registros.")
    return [_normalize_row(dict(row)) for row in rows]


def _parse_excel_backup(file) -> list[dict[str, Any]]:
    df = pd.read_excel(file)
    if df.empty:
        return []
    renamed = df.rename(columns={column: DISPLAY_TO_INTERNAL.get(str(column), str(column)) for column in df.columns})
    missing = [column for column in ["id", "codigo_monitoramento", "tipo_registro", "data_hora_registro"] if column not in renamed.columns]
    if missing:
        raise ValueError(
            "Excel nao parece ser um backup do banco. Use o arquivo JSON de backup ou exporte novamente pelo botao da aba de recuperacao."
        )
    return [_normalize_row(dict(row)) for _, row in renamed.iterrows()]


def parse_backup_file(file_name: str, content: bytes, uploaded_file=None) -> list[dict[str, Any]]:
    lower = str(file_name or "").lower()
    if lower.endswith(".json"):
        return _parse_json_backup(content)
    if lower.endswith((".xlsx", ".xls")):
        return _parse_excel_backup(uploaded_file)
    raise ValueError("Formato nao suportado. Use .json ou .xlsx.")


def _existing_ids(conn, ids: list[Any]) -> set[str]:
    ids = [str(item) for item in ids if item not in [None, ""]]
    if not ids:
        return set()
    found: set[str] = set()
    for start in range(0, len(ids), 900):
        batch = ids[start : start + 900]
        placeholders = ", ".join("?" for _ in batch)
        rows = conn.execute(
            f"select cast(id as text) as id_text from ots_otd_registros where cast(id as text) in ({placeholders})",
            batch,
        ).fetchall()
        found.update(str(row["id_text"] if isinstance(row, dict) else row[0]) for row in rows)
    return found


def restore_backup_rows(rows: list[dict[str, Any]], mode: str = "merge") -> dict[str, Any]:
    mode = "replace" if mode == "replace" else "merge"
    if not rows:
        return {"status": "BLOQUEADO_BACKUP_VAZIO", "restored": 0, "ignored": 0, "errors": ["Backup sem registros. Banco atual preservado."]}
    rows = [_normalize_row(row) for row in rows]
    columns = list(BACKUP_COLUMNS)
    restored = ignored = errors = 0
    with get_connection() as conn:
        if mode == "replace":
            conn.execute("delete from ots_otd_registros")
            existing = set()
        else:
            existing = _existing_ids(conn, [row.get("id") for row in rows])
        placeholders = ", ".join("?" for _ in columns)
        columns_sql = ", ".join(columns)
        insert_sql = f"insert into ots_otd_registros ({columns_sql}) values ({placeholders})"
        for row in rows:
            row_id = str(row.get("id") or "")
            if mode == "merge" and row_id and row_id in existing:
                ignored += 1
                continue
            try:
                conn.execute(insert_sql, tuple(row.get(column) for column in columns))
                restored += 1
            except Exception:
                errors += 1
                ignored += 1
    status = "SUCESSO" if errors == 0 else "PARCIAL"
    return {"status": status, "restored": restored, "ignored": ignored, "errors": errors}

