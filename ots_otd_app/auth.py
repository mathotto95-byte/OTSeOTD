from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any


def _read_users_from_secrets() -> dict[str, str]:
    try:
        import streamlit as st

        users = st.secrets.get("users", {})
        if users:
            return {str(username).strip(): str(password) for username, password in dict(users).items()}
        auth = st.secrets.get("auth", {})
        if auth and auth.get("users"):
            return {str(username).strip(): str(password) for username, password in dict(auth.get("users")).items()}
        users_json = st.secrets.get("USERS_JSON")
        if users_json:
            payload = json.loads(str(users_json))
            return {str(username).strip(): str(password) for username, password in dict(payload).items()}
    except Exception:
        pass
    users_json = os.getenv("USERS_JSON", "")
    if users_json:
        try:
            payload = json.loads(users_json)
            return {str(username).strip(): str(password) for username, password in dict(payload).items()}
        except Exception:
            return {}
    return {}


def configured_users() -> dict[str, str]:
    users = {username: password for username, password in _read_users_from_secrets().items() if username}
    return users or {"admin": "admin"}


def using_default_admin() -> bool:
    return not bool(_read_users_from_secrets())


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _password_matches(stored: str, supplied: str) -> bool:
    stored = str(stored or "")
    supplied = str(supplied or "")
    if stored.startswith("sha256:"):
        return hmac.compare_digest(stored.removeprefix("sha256:"), _sha256(supplied))
    return hmac.compare_digest(stored, supplied)


def authenticate(username: object, password: object) -> bool:
    user = str(username or "").strip()
    if not user:
        return False
    stored = configured_users().get(user)
    if stored is None:
        return False
    return _password_matches(stored, str(password or ""))

