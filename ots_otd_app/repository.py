from __future__ import annotations

import json
from typing import Any

import pandas as pd

from ots_otd_app.database import get_connection, read_sql
from ots_otd_app.service import comparar_alteracoes, dados_alterados_json, now_iso, validar_campos_obrigatorios


TABLE_NAME = "ots_otd_registros"
DEFAULT_LIST_LIMIT = 500


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row else None


def _latest_rows_sql() -> str:
    return f"""
        (
            select *,
                   row_number() over (
                       partition by codigo_monitoramento
                       order by data_hora_registro desc, id desc
                   ) as linha_atual
            from {TABLE_NAME}
        ) registros_atuais
    """


def buscar_registro_mais_recente(codigo_monitoramento: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            f"""
            select *
            from {TABLE_NAME}
            where codigo_monitoramento = ?
            order by data_hora_registro desc, id desc
            limit 1
            """,
            (codigo_monitoramento,),
        ).fetchone()
    return _row_to_dict(row)


def verificar_registro_original_existente(codigo_monitoramento: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            f"""
            select 1
            from {TABLE_NAME}
            where codigo_monitoramento = ? and tipo_registro = 'ORIGINAL'
            limit 1
            """,
            (codigo_monitoramento,),
        ).fetchone()
    return bool(row)


def _insert_record(conn, payload: dict[str, Any]) -> int:
    columns = [
        "previsao_carga",
        "data_limite",
        "agendamento_carga",
        "agenda_gfl",
        "codigo_monitoramento",
        "tipo_registro",
        "data_hora_registro",
        "usuario_registro",
        "registro_origem_id",
        "dados_alterados",
        "created_at",
        "updated_at",
    ]
    placeholders = ", ".join("?" for _ in columns)
    sql = f"insert into {TABLE_NAME} ({', '.join(columns)}) values ({placeholders})"
    values = tuple(payload.get(column) for column in columns)
    if conn.db_type == "postgres":
        row = conn.execute(sql + " returning id", values).fetchone()
        return int(row["id"] if isinstance(row, dict) else row[0])
    cursor = conn.execute(sql, values)
    return int(cursor.lastrowid or 0)


def incluir_registro_original(dados: dict[str, Any], usuario: str) -> int:
    missing = validar_campos_obrigatorios(dados)
    if missing:
        raise ValueError("Campos obrigatorios nao preenchidos: " + ", ".join(missing))
    codigo = str(dados.get("codigo_monitoramento") or "")
    with get_connection() as conn:
        duplicate = conn.execute(
            f"""
            select 1
            from {TABLE_NAME}
            where codigo_monitoramento = ? and tipo_registro = 'ORIGINAL'
            limit 1
            """,
            (codigo,),
        ).fetchone()
        if duplicate:
            raise ValueError("Este codigo de monitoramento ja possui registro original.")
        now = now_iso()
        payload = {
            **dados,
            "tipo_registro": "ORIGINAL",
            "data_hora_registro": now,
            "usuario_registro": usuario,
            "registro_origem_id": None,
            "dados_alterados": "{}",
            "created_at": now,
            "updated_at": now,
        }
        return _insert_record(conn, payload)


def incluir_registro_alterado(registro_anterior: dict[str, Any], novos_dados: dict[str, Any], usuario: str) -> int:
    missing = validar_campos_obrigatorios(novos_dados)
    if missing:
        raise ValueError("Campos obrigatorios nao preenchidos: " + ", ".join(missing))
    changes = comparar_alteracoes(registro_anterior, novos_dados)
    if not changes:
        raise ValueError("Nenhuma alteracao foi identificada.")
    now = now_iso()
    previous_id = int(registro_anterior.get("id") or 0)
    with get_connection() as conn:
        payload = {
            **novos_dados,
            "tipo_registro": "ALTERADO",
            "data_hora_registro": now,
            "usuario_registro": usuario,
            "registro_origem_id": previous_id,
            "dados_alterados": dados_alterados_json(changes),
            "created_at": now,
            "updated_at": now,
        }
        return _insert_record(conn, payload)


def salvar_payload_com_historico(dados: dict[str, Any], usuario: str) -> tuple[str, int | None, str]:
    anterior = buscar_registro_mais_recente(str(dados.get("codigo_monitoramento") or ""))
    if not anterior:
        return "incluido", incluir_registro_original(dados, usuario), ""
    changes = comparar_alteracoes(anterior, dados)
    if not changes:
        return "ignorado", None, "Sem alteracao"
    return "alterado", incluir_registro_alterado(anterior, dados, usuario), ""


def _build_where(filtros: dict[str, Any] | None = None) -> tuple[str, list[Any]]:
    filtros = filtros or {}
    where = []
    params: list[Any] = []
    codigo = str(filtros.get("codigo_monitoramento") or "").strip()
    if codigo:
        where.append("codigo_monitoramento like ?")
        params.append(f"%{codigo}%")
    status = str(filtros.get("status") or "").strip()
    if status:
        where.append("tipo_registro = ?")
        params.append(status)
    usuario = str(filtros.get("usuario_registro") or "").strip()
    if usuario:
        where.append("usuario_registro = ?")
        params.append(usuario)
    data_inicial = str(filtros.get("data_inicial") or "").strip()
    if data_inicial:
        where.append("substr(data_hora_registro, 1, 10) >= ?")
        params.append(data_inicial)
    data_final = str(filtros.get("data_final") or "").strip()
    if data_final:
        where.append("substr(data_hora_registro, 1, 10) <= ?")
        params.append(data_final)
    busca = str(filtros.get("busca") or "").strip()
    if busca:
        where.append(
            """
            (
                codigo_monitoramento like ? or previsao_carga like ? or data_limite like ?
                or agendamento_carga like ? or agenda_gfl like ? or usuario_registro like ?
            )
            """
        )
        like = f"%{busca}%"
        params.extend([like, like, like, like, like, like])
    where_sql = f"where {' and '.join(where)}" if where else ""
    return where_sql, params


def listar_registros_ots_otd(filtros: dict[str, Any] | None = None, limit: int | None = DEFAULT_LIST_LIMIT) -> pd.DataFrame:
    where_sql, params = _build_where(filtros)
    limit_sql = ""
    if limit and int(limit) > 0:
        limit_sql = "limit ?"
        params = [*params, int(limit)]
    return read_sql(
        f"""
        select *
        from {TABLE_NAME}
        {where_sql}
        order by data_hora_registro desc, id desc
        {limit_sql}
        """,
        tuple(params),
    )


def contar_registros_ots_otd(filtros: dict[str, Any] | None = None) -> int:
    where_sql, params = _build_where(filtros)
    with get_connection() as conn:
        row = conn.execute(
            f"""
            select count(*) as total
            from {TABLE_NAME}
            {where_sql}
            """,
            tuple(params),
        ).fetchone()
    return int(row["total"] if isinstance(row, dict) else row[0])


def contar_registros_atuais_ots_otd(filtros: dict[str, Any] | None = None) -> int:
    where_sql, params = _build_where(filtros)
    current_where = f"{where_sql} and linha_atual = 1" if where_sql else "where linha_atual = 1"
    with get_connection() as conn:
        row = conn.execute(
            f"""
            select count(*) as total
            from {_latest_rows_sql()}
            {current_where}
            """,
            tuple(params),
        ).fetchone()
    return int(row["total"] if isinstance(row, dict) else row[0])


def contar_pendentes_agenda_gfl(filtros: dict[str, Any] | None = None) -> int:
    where_sql, params = _build_where(filtros)
    extra = "where linha_atual = 1 and" if not where_sql else f"{where_sql} and linha_atual = 1 and"
    with get_connection() as conn:
        row = conn.execute(
            f"""
            select count(*) as total
            from {_latest_rows_sql()}
            {extra} trim(coalesce(agenda_gfl, '')) = ''
            """,
            tuple(params),
        ).fetchone()
    return int(row["total"] if isinstance(row, dict) else row[0])


def listar_pendentes_agenda_gfl(filtros: dict[str, Any] | None = None, limit: int | None = DEFAULT_LIST_LIMIT) -> pd.DataFrame:
    where_sql, params = _build_where(filtros)
    current_where = (
        f"{where_sql} and linha_atual = 1 and trim(coalesce(agenda_gfl, '')) = ''"
        if where_sql
        else "where linha_atual = 1 and trim(coalesce(agenda_gfl, '')) = ''"
    )
    limit_sql = ""
    if limit and int(limit) > 0:
        limit_sql = "limit ?"
        params = [*params, int(limit)]
    return read_sql(
        f"""
        select *
        from {_latest_rows_sql()}
        {current_where}
        order by data_hora_registro desc, id desc
        {limit_sql}
        """,
        tuple(params),
    )


def listar_historico_monitoramento(codigo_monitoramento: str) -> pd.DataFrame:
    return read_sql(
        f"""
        select *
        from {TABLE_NAME}
        where codigo_monitoramento = ?
        order by data_hora_registro desc, id desc
        """,
        (codigo_monitoramento,),
    )


def usuarios_com_registros() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            select distinct usuario_registro
            from {TABLE_NAME}
            where coalesce(usuario_registro, '') <> ''
            order by usuario_registro
            """
        ).fetchall()
    return [str(row["usuario_registro"]) for row in rows]


def parse_dados_alterados(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or "{}")
    except Exception:
        return {}

