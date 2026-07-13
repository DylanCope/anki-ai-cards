"""Signed session-cookie auth.

Only one Google account (`ALLOWED_EMAIL`) can ever hold a session — the OAuth
callback in `app/api/auth.py` rejects any other email before a session cookie
is issued — so `require_auth` just needs to verify the cookie's signature and
freshness, not re-check an allowlist on every request.

`require_auth` also accepts `Authorization: Bearer <DEV_API_KEY>` as an
alternate credential, so scripts/loop iterations can call the API without a
browser OAuth flow. Only active when the `DEV_API_KEY` env var is set (unset
in any environment that hasn't opted in) — see AGENTS.md for how it's
provisioned.
"""

import os
import secrets
from datetime import timedelta

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE_SECONDS = int(timedelta(days=30).total_seconds())


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(os.environ["SESSION_SECRET_KEY"], salt="session")


def create_session_cookie(email: str) -> str:
    return _serializer().dumps({"email": email})


def verify_session_cookie(token: str) -> str | None:
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("email")


def _verify_dev_api_key(request: Request) -> str | None:
    dev_key = os.environ.get("DEV_API_KEY")
    if not dev_key:
        return None
    header = request.headers.get("Authorization", "")
    scheme, _, presented = header.partition(" ")
    if scheme != "Bearer" or not presented:
        return None
    if not secrets.compare_digest(presented, dev_key):
        return None
    return os.environ["ALLOWED_EMAIL"]


def require_auth(request: Request) -> str:
    """FastAPI dependency: protects a route behind a valid session cookie or
    the `DEV_API_KEY` bearer token."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    email = verify_session_cookie(token) if token else None
    if email is None:
        email = _verify_dev_api_key(request)
    if email is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return email
