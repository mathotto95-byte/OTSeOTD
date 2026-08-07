from __future__ import annotations

import base64
import json
import os
import time
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

from ots_otd_app.database import get_connection, get_database_config, read_sql
from ots_otd_app.time_utils import now, now_iso


BACKUP_COLUMNS = [
    "id",
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


SECRET_ALIASES = {
    "GITHUB_TOKEN": ["GITHUB_TOKEN", "github_token", "token"],
    "GITHUB_REPOSITORY": ["GITHUB_REPOSITORY", "github_repository", "repository", "repo"],
    "GITHUB_BRANCH": ["GITHUB_BRANCH", "github_branch", "branch"],
    "GITHUB_BACKUP_PATH": ["GITHUB_BACKUP_PATH", "github_backup_path", "backup_path", "latest_path"],
    "GITHUB_AUTO_BACKUP": ["GITHUB_AUTO_BACKUP", "github_auto_backup", "auto_backup"],
}


def _read_secret(name: str, default: str = "") -> str:
    candidates = SECRET_ALIASES.get(name, [name])
    try:
        import streamlit as st

        for candidate in candidates:
            value = st.secrets.get(candidate)
            if value not in [None, ""]:
                return str(value).strip()
        github = st.secrets.get("github", {})
        if github:
            for candidate in candidates:
                value = github.get(candidate)
                if value not in [None, ""]:
                    return str(value).strip()
    except Exception:
        pass
    for candidate in candidates:
        value = os.getenv(candidate)
        if value not in [None, ""]:
            return str(value).strip()
    return default


def _sanitize_token(value: str) -> str:
    token = str(value or "").strip().strip('"').strip("'")
    for prefix in ["Bearer ", "bearer ", "token ", "Token "]:
        if token.startswith(prefix):
            token = token[len(prefix) :].strip()
    return token


def _token_is_placeholder(token: str) -> bool:
    cleaned = str(token or "").strip()
    return bool(cleaned) and ("..." in cleaned or cleaned in {"github_pat_", "ghp_", "gho_"})


def _mask_token(token: str) -> str:
    cleaned = str(token or "").strip()
    if not cleaned:
        return "nao configurado"
    if len(cleaned) <= 12:
        return "***"
    return f"{cleaned[:10]}...{cleaned[-4:]}"


def _yes(value: object, default: bool = False) -> bool:
    text = str(value or "").strip().upper()
    if not text:
        return default
    return text in {"1", "SIM", "S", "TRUE", "YES", "ON"}


def github_settings() -> dict[str, Any]:
    return {
        "token": _sanitize_token(_read_secret("GITHUB_TOKEN")),
        "repository": _read_secret("GITHUB_REPOSITORY", "mathotto95-byte/OTSeOTD"),
        "branch": _read_secret("GITHUB_BRANCH", "main"),
        "latest_path": _read_secret("GITHUB_BACKUP_PATH", "backups/ots_otd_latest.json"),
        "auto_backup": _yes(_read_secret("GITHUB_AUTO_BACKUP", "SIM"), True),
    }


def github_backup_configured() -> bool:
    settings = github_settings()
    return bool(settings["token"] and not _token_is_placeholder(settings["token"]) and settings["repository"] and settings["branch"])


def github_auto_backup_enabled() -> bool:
    settings = github_settings()
    return bool(github_backup_configured() and settings["auto_backup"])


def _api_url(repository: str, path: str) -> str:
    safe_path = "/".join(quote(part) for part in path.strip("/").split("/"))
    return f"https://api.github.com/repos/{repository}/contents/{safe_path}"


def _repo_api_url(repository: str) -> str:
    return f"https://api.github.com/repos/{quote(repository, safe='/')}"


def _build_request(method: str, url: str, token: str, payload: dict[str, Any] | None, auth_scheme: str) -> Request:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, method=method)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Authorization", f"{auth_scheme} {token}")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    return request


def _request_json(method: str, url: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    last_unauthorized: HTTPError | None = None
    for auth_scheme in ["Bearer", "token"]:
        request = _build_request(method, url, token, payload, auth_scheme)
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except HTTPError as exc:
            if exc.code == 401 and auth_scheme == "Bearer":
                last_unauthorized = exc
                continue
            raise
    if last_unauthorized:
        raise last_unauthorized
    return {}


def _request_bytes(method: str, url: str, token: str, payload: dict[str, Any] | None = None) -> bytes:
    request = _build_request(method, url, token, payload, "Bearer")
    with urlopen(request, timeout=30) as response:
        return response.read()


def _remote_sha(settings: dict[str, Any], path: str) -> str:
    url = _api_url(settings["repository"], path) + f"?ref={quote(settings['branch'])}"
    try:
        result = _request_json("GET", url, settings["token"])
        return str(result.get("sha") or "")
    except HTTPError as exc:
        if exc.code == 404:
            return ""
        raise


def _download_text(settings: dict[str, Any], path: str) -> str:
    url = _api_url(settings["repository"], path) + f"?ref={quote(settings['branch'])}"
    result = _request_json("GET", url, settings["token"])
    content = str(result.get("content") or "").replace("\n", "")
    encoding = str(result.get("encoding") or "")
    if encoding == "base64":
        return base64.b64decode(content.encode("ascii")).decode("utf-8")
    return content


def _upload_bytes(settings: dict[str, Any], path: str, content: bytes, message: str, retries: int = 3) -> dict[str, Any]:
    last_error: HTTPError | None = None
    for attempt in range(max(int(retries or 1), 1)):
        payload = {
            "message": message,
            "content": base64.b64encode(content).decode("ascii"),
            "branch": settings["branch"],
        }
        sha = _remote_sha(settings, path)
        if sha:
            payload["sha"] = sha
        try:
            return _request_json("PUT", _api_url(settings["repository"], path), settings["token"], payload)
        except HTTPError as exc:
            last_error = exc
            if exc.code != 409 or attempt >= retries - 1:
                raise
            time.sleep(0.8 + attempt * 0.8)
    if last_error:
        raise last_error
    return {}


def _github_http_error_message(exc: HTTPError) -> str:
    if exc.code == 401:
        return (
            "GitHub recusou o token: token invalido, expirado ou sem acesso. "
            "No Streamlit Secrets use GITHUB_TOKEN = \"github_pat_...\" ou [github] token = \"github_pat_...\"."
        )
    if exc.code == 403:
        return (
            "GitHub recusou por permissao. O token precisa ter acesso ao repositorio e permissao "
            "Contents: Read and write."
        )
    if exc.code == 404:
        return "GitHub nao encontrou o repositorio, branch ou arquivo de backup configurado."
    return str(exc)


def github_diagnostic() -> dict[str, Any]:
    settings = github_settings()
    token = settings["token"]
    return {
        "repository": settings["repository"],
        "branch": settings["branch"],
        "latest_path": settings["latest_path"],
        "destination": f"{settings['repository']}/{settings['latest_path']}",
        "destination_type": "Arquivo JSON no repositorio GitHub, nao GitHub Release",
        "token_masked": _mask_token(token),
        "token_length": len(token),
        "token_placeholder": _token_is_placeholder(token),
        "configured": github_backup_configured(),
    }


def test_github_connection() -> dict[str, Any]:
    settings = github_settings()
    diagnostic = github_diagnostic()
    if not settings["token"]:
        return {"status": "NAO_CONFIGURADO", "message": "GITHUB_TOKEN nao configurado nos Secrets.", **diagnostic}
    if _token_is_placeholder(settings["token"]):
        return {
            "status": "TOKEN_INVALIDO",
            "message": "O GITHUB_TOKEN parece estar como exemplo/placeholder. Cole o token completo gerado no GitHub, sem reticencias.",
            **diagnostic,
        }
    try:
        repo = _request_json("GET", _repo_api_url(settings["repository"]), settings["token"])
        _remote_sha(settings, settings["latest_path"])
    except HTTPError as exc:
        return {"status": "ERRO", "message": _github_http_error_message(exc), **diagnostic}
    except (URLError, TimeoutError) as exc:
        return {"status": "ERRO", "message": str(exc), **diagnostic}
    return {
        "status": "SUCESSO",
        "message": "GitHub conectado. Token autenticou e o repositorio foi localizado.",
        "repo_private": bool(repo.get("private")),
        **diagnostic,
    }


def _all_records() -> pd.DataFrame:
    return read_sql(
        """
        select id, previsao_carga, data_limite, agendamento_carga, agenda_gfl,
               codigo_monitoramento, tipo_registro, data_hora_registro,
               usuario_registro, registro_origem_id, dados_alterados, created_at, updated_at
        from ots_otd_registros
        order by id
        """
    )


def _backup_payload(df: pd.DataFrame) -> dict[str, Any]:
    rows = json.loads(df.where(pd.notna(df), None).to_json(orient="records", force_ascii=False))
    return {
        "schema": "ots_otd_backup_v1",
        "generated_at": now_iso(),
        "records": int(len(rows)),
        "rows": rows,
    }


def backup_to_github(reason: str = "manual") -> dict[str, Any]:
    settings = github_settings()
    if _token_is_placeholder(settings["token"]):
        return {
            "status": "TOKEN_INVALIDO",
            "message": "GITHUB_TOKEN invalido: o valor parece estar incompleto ou com reticencias. Use o token completo gerado no GitHub.",
            "records": 0,
        }
    if not github_backup_configured():
        return {"status": "NAO_CONFIGURADO", "message": "Configure GITHUB_TOKEN para habilitar backup no GitHub.", "records": 0}
    if get_database_config().db_type == "postgres":
        return {"status": "IGNORADO_SUPABASE", "message": "Banco principal em Supabase. Backup GitHub fica desnecessario.", "records": 0}
    df = _all_records()
    if df.empty:
        return {"status": "IGNORADO_BASE_VAZIA", "message": "Backup GitHub ignorado: base local vazia.", "records": 0}
    payload = _backup_payload(df)
    content = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    stamp = now().strftime("%Y%m%d_%H%M%S_%f")
    history_path = f"backups/history/{stamp}_{uuid.uuid4().hex[:8]}_ots_otd.json"
    try:
        _upload_bytes(settings, settings["latest_path"], content, f"Backup OTS/OTD latest ({reason})")
        _upload_bytes(settings, history_path, content, f"Backup OTS/OTD historico ({reason})", retries=1)
    except HTTPError as exc:
        return {"status": "ERRO", "message": _github_http_error_message(exc), "records": int(len(df))}
    except (URLError, TimeoutError) as exc:
        return {"status": "ERRO", "message": str(exc), "records": int(len(df))}
    return {"status": "SUCESSO", "message": f"Backup enviado para {settings['latest_path']}.", "records": int(len(df))}


def restore_from_github_if_empty() -> dict[str, Any]:
    if not github_backup_configured():
        return {"status": "NAO_CONFIGURADO", "message": "GitHub backup nao configurado.", "records": 0}
    if get_database_config().db_type == "postgres":
        return {"status": "IGNORADO_SUPABASE", "message": "Banco principal em Supabase.", "records": 0}
    settings = github_settings()
    with get_connection() as conn:
        row = conn.execute("select count(*) as total from ots_otd_registros").fetchone()
        total = int(row["total"] if isinstance(row, dict) else row[0])
        if total > 0:
            return {"status": "IGNORADO_BASE_COM_DADOS", "message": "Base local ja possui dados.", "records": total}
    try:
        raw = _download_text(settings, settings["latest_path"])
        payload = json.loads(raw)
        rows = payload.get("rows") or []
        if not rows:
            return {"status": "IGNORADO_BACKUP_VAZIO", "message": "Backup GitHub sem registros.", "records": 0}
        with get_connection() as conn:
            placeholders = ", ".join("?" for _ in BACKUP_COLUMNS)
            columns_sql = ", ".join(BACKUP_COLUMNS)
            conn.executemany(
                f"insert or ignore into ots_otd_registros ({columns_sql}) values ({placeholders})",
                [tuple(row.get(column) for column in BACKUP_COLUMNS) for row in rows],
            )
    except HTTPError as exc:
        if exc.code == 404:
            return {"status": "NAO_ENCONTRADO", "message": "Nenhum backup latest encontrado no GitHub.", "records": 0}
        return {"status": "ERRO", "message": _github_http_error_message(exc), "records": 0}
    except Exception as exc:
        return {"status": "ERRO", "message": str(exc), "records": 0}
    return {"status": "RESTAURADO", "message": "Backup GitHub restaurado no SQLite local.", "records": int(len(rows))}
