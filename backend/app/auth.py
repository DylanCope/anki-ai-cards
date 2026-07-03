"""Signed session-cookie auth.

Only one Google account (`ALLOWED_EMAIL`) can ever hold a session — the OAuth
callback in `app/api/auth.py` rejects any other email before a session cookie
is issued — so `require_auth` just needs to verify the cookie's signature and
freshness, not re-check an allowlist on every request.
"""

import os
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


def require_auth(request: Request) -> str:
    """FastAPI dependency: protects a route behind a valid session cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    email = verify_session_cookie(token) if token else None
    if email is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return email
