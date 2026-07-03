"""Google OAuth + Docs API client.

OAuth serves double duty here: the same flow both logs Dylan into the app and
grants read-only access to the lesson doc (see PRD Requirements/Auth). This
module only talks to Google's HTTP endpoints; session/cookie handling and the
`ALLOWED_EMAIL` check live in the auth routes (task 6).
"""

import os
from urllib.parse import urlencode

import httpx

AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DOCS_API_BASE_URL = "https://docs.googleapis.com/v1"

SCOPES = "openid email https://www.googleapis.com/auth/documents.readonly"


def _client_id() -> str:
    return os.environ["GOOGLE_CLIENT_ID"]


def _client_secret() -> str:
    return os.environ["GOOGLE_CLIENT_SECRET"]


def build_authorize_url(redirect_uri: str, state: str) -> str:
    """Build the Google consent-screen URL to redirect the browser to."""
    params = {
        "client_id": _client_id(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        # "offline" + "consent" so a refresh_token is issued every login,
        # not just the first time this Google account authorizes the app.
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{AUTH_BASE_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str, redirect_uri: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    response.raise_for_status()
    return response.json()


async def refresh_access_token(refresh_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "grant_type": "refresh_token",
            },
        )
    response.raise_for_status()
    return response.json()


async def fetch_document(document_id: str, access_token: str) -> dict:
    """Fetch the raw Docs API JSON for a document."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DOCS_API_BASE_URL}/documents/{document_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    response.raise_for_status()
    return response.json()


def flatten_runs(doc_json: dict) -> list[dict]:
    """Flatten a Docs API document into a flat list of `{text, color}` spans.

    Walks each paragraph's `elements` in document order and emits one span per
    `textRun`, so the freeform lesson-doc layout (English phrase / Dylan's
    attempt / teacher's red-marked correction, in no fixed structure) can be
    handed to the inner agent as plain data instead of raw Docs JSON. `color`
    is `"red"` when the run's foreground color reads as red text — the color
    the teacher uses to mark mistakes — otherwise `None`.
    """
    spans = []
    for element in doc_json.get("body", {}).get("content", []):
        paragraph = element.get("paragraph")
        if paragraph is None:
            continue
        for para_element in paragraph.get("elements", []):
            text_run = para_element.get("textRun")
            if text_run is None:
                continue
            spans.append(
                {
                    "text": text_run.get("content", ""),
                    "color": _classify_color(text_run.get("textStyle", {})),
                }
            )
    return spans


def _classify_color(text_style: dict) -> str | None:
    rgb = text_style.get("foregroundColor", {}).get("color", {}).get("rgbColor", {})
    if not rgb:
        return None
    red = rgb.get("red", 0.0)
    green = rgb.get("green", 0.0)
    blue = rgb.get("blue", 0.0)
    if red > 0.5 and red - green > 0.2 and red - blue > 0.2:
        return "red"
    return None
