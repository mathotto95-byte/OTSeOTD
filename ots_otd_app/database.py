from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
DB_PATH = Path(os.getenv("OTS_OTD_DB_PATH", DATA_DIR / "ots_otd.sqlite3")).expanduser()
_INIT_LOCK = threading.Lock()
_INITIALIZED = False


@dataclass(frozen=True)
class DatabaseConfig:
    db_type: str
    database_url: str = ""
    sqlite_path: Path = DB_PATH


def _read_secret(name: str) -> str:
    try:
        import streamlit as st

        value = st.secrets.get(name)
        if value:
            return str(value)
        database = st.secrets.get("database", {})
        if database and database.get(name):
            return str(database.get(name))
    except Exception:
        pass
    return os.getenv(name, "")


def get_database_config() -> DatabaseConfig:
    database_url = _read_secret("DATABASE_URL").strip()
    if database_url:
        return DatabaseConfig(db_type="postgres", database_url=database_url)
    return DatabaseConfig(db_type="sqlite", sqlite_path=DB_PATH)


def _translate(sql: str) -> str:
    return sql.replace("?", "%s")


class DbConnection:
    def __init__(self, raw, db_type: str) -> None:
        self.raw = raw
        self.db_type = db_type

    def execute(self, sql: str, params: tuple | list | None = None):
        return self.raw.execute(_translate(sql) if self.db_type == "postgres" else sql, params or ())

    def executemany(self, sql: str, params: list[tuple] | tuple[tuple, ...]):
        return self.raw.executemany(_translate(sql) if self.db_type == "postgres" else sql, params)

    def commit(self) -> None:
        self.raw.commit()

    def rollback(self) -> None:
        self.raw.rollback()

    def close(self) -> None:
        self.raw.close()


def _connect_sqlite(path: Path = DB_PATH) -> DbConnection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    conn.execute("pragma journal_mode = wal")
    conn.execute("pragma busy_timeout = 30000")
    conn.execute("pragma wal_autocheckpoint = 1000")
    return DbConnection(conn, "sqlite")


def _connect_postgres(database_url: str) -> DbConnection:
    import psycopg2
    from psycopg2.extras import DictCursor

    conn = psycopg2.connect(database_url, cursor_factory=DictCursor)
    return DbConnection(conn, "postgres")


def connect() -> DbConnection:
    config = get_database_config()
    if config.db_type == "postgres":
        return _connect_postgres(config.database_url)
    return _connect_sqlite(config.sqlite_path)


def _create_schema_sqlite(conn: DbConnection) -> None:
    conn.execute(
        """
        create table if not exists ots_otd_registros (
            id integer primary key autoincrement,
            previsao_carga text not null,
            data_limite text not null,
            agendamento_carga text not null,
            agenda_gfl text not null default '',
            codigo_monitoramento text not null,
            tipo_registro text not null,
            data_hora_registro text not null,
            usuario_registro text not null,
            registro_origem_id integer,
            dados_alterados text,
            created_at text,
            updated_at text
        )
        """
    )


def _create_schema_postgres(conn: DbConnection) -> None:
    conn.execute(
        """
        create table if not exists ots_otd_registros (
            id bigserial primary key,
            previsao_carga text not null,
            data_limite text not null,
            agendamento_carga text not null,
            agenda_gfl text not null default '',
            codigo_monitoramento text not null,
            tipo_registro text not null,
            data_hora_registro text not null,
            usuario_registro text not null,
            registro_origem_id bigint,
            dados_alterados text,
            created_at text,
            updated_at text
        )
        """
    )


def initialize_database(force: bool = False) -> None:
    global _INITIALIZED
    if _INITIALIZED and not force:
        return
    with _INIT_LOCK:
        if _INITIALIZED and not force:
            return
        with get_connection(initialize=False) as conn:
            if conn.db_type == "postgres":
                _create_schema_postgres(conn)
            else:
                _create_schema_sqlite(conn)
            conn.execute("create index if not exists idx_ots_otd_codigo on ots_otd_registros(codigo_monitoramento)")
            conn.execute("create index if not exists idx_ots_otd_data on ots_otd_registros(data_hora_registro desc)")
            conn.execute("create index if not exists idx_ots_otd_status on ots_otd_registros(tipo_registro)")
            conn.execute("create index if not exists idx_ots_otd_usuario on ots_otd_registros(usuario_registro)")
            conn.execute("create index if not exists idx_ots_otd_agenda_gfl on ots_otd_registros(agenda_gfl)")
            conn.execute(
                """
                create unique index if not exists ux_ots_otd_original_codigo
                on ots_otd_registros(codigo_monitoramento)
                where tipo_registro = 'ORIGINAL'
                """
            )
        _INITIALIZED = True


@contextmanager
def get_connection(initialize: bool = True) -> Iterator[DbConnection]:
    if initialize:
        initialize_database()
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def read_sql(sql: str, params: tuple | list | None = None) -> pd.DataFrame:
    with get_connection() as conn:
        cursor = conn.execute(sql, params or ())
        rows = cursor.fetchall()
        columns = [item[0] for item in cursor.description] if cursor.description else []
    return pd.DataFrame([dict(row) for row in rows], columns=columns)


def database_status() -> dict[str, Any]:
    config = get_database_config()
    try:
        with get_connection() as conn:
            row = conn.execute("select count(*) as total from ots_otd_registros").fetchone()
            total = int(row["total"] if isinstance(row, dict) else row[0])
        return {
            "connected": True,
            "db_type": config.db_type,
            "database": "Supabase/PostgreSQL" if config.db_type == "postgres" else str(config.sqlite_path),
            "rows": total,
            "error": "",
        }
    except Exception as exc:
        return {
            "connected": False,
            "db_type": config.db_type,
            "database": "Supabase/PostgreSQL" if config.db_type == "postgres" else str(config.sqlite_path),
            "rows": 0,
            "error": str(exc),
        }

