"""Google OAuth login/callback routes.

OAuth serves double duty here: the same consent flow both logs Dylan into the
app and grants read-only Docs API access (see PRD Auth). `/auth/google/login`
kicks off the redirect; `/auth/google/callback` finishes it, rejecting any
email other than `ALLOWED_EMAIL` before a token is ever stored or a session
cookie issued.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.auth import SESSION_COOKIE_NAME, SESSION_MAX_AGE_SECONDS, create_session_cookie
from app.clients import google_docs
from app.models import OAuthToken, get_engine

router = APIRouter(prefix="/auth/google", tags=["auth"])

STATE_COOKIE_NAME = "oauth_state"
STATE_COOKIE_MAX_AGE_SECONDS = 600


def _redirect_uri() -> str:
    # Deliberately not derived from the incoming Request (e.g. request.url_for):
    # every request arrives via the frontend's server-side rewrite proxy
    # (next.config.ts), so the backend only ever sees that proxy's own address
    # as its "incoming" host — in production that's the private
    # anki-ai-cards-backend.internal 6PN address, which neither Google nor the
    # user's browser can resolve. The redirect_uri must be the public origin
    # the *browser* actually navigates on, which is the frontend's — that's
    # also required for the session cookie set at the end of this flow to land
    # on the right origin (same reasoning as the rewrite proxy itself).
    return f"{os.environ['PUBLIC_APP_URL'].rstrip('/')}/auth/google/callback"


@router.get("/login")
async def google_login() -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    auth_url = google_docs.build_authorize_url(_redirect_uri(), state)
    response = RedirectResponse(auth_url)
    response.set_cookie(
        STATE_COOKIE_NAME,
        state,
        max_age=STATE_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/callback", name="google_callback")
async def google_callback(request: Request, code: str, state: str) -> RedirectResponse:
    expected_state = request.cookies.get(STATE_COOKIE_NAME)
    if not expected_state or state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    tokens = await google_docs.exchange_code_for_tokens(code, _redirect_uri())
    userinfo = await google_docs.fetch_userinfo(tokens["access_token"])
    email = userinfo.get("email")

    if email != os.environ["ALLOWED_EMAIL"]:
        raise HTTPException(status_code=403, detail="Email not allowed")

    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=tokens.get("expires_in", 3600)
    )
    engine = get_engine()
    with Session(engine) as session:
        record = session.exec(
            select(OAuthToken).where(OAuthToken.email == email)
        ).first()
        if record is None:
            record = OAuthToken(
                email=email,
                access_token=tokens["access_token"],
                refresh_token=tokens["refresh_token"],
                expires_at=expires_at,
            )
        else:
            record.access_token = tokens["access_token"]
            record.refresh_token = tokens["refresh_token"]
            record.expires_at = expires_at
        session.add(record)
        session.commit()

    response = RedirectResponse("/")
    response.delete_cookie(STATE_COOKIE_NAME)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_cookie(email),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return response
