import pytest
import respx
from httpx import Response

from app.clients import google_docs

GOOGLE_CLIENT_ID = "test-client-id"
GOOGLE_CLIENT_SECRET = "test-client-secret"

# Hand-written fixture shaped like a real Docs API `documents.get` response:
# one paragraph with a plain English phrase, one paragraph with a black
# attempt followed by a red-text correction run.
DOC_FIXTURE = {
    "body": {
        "content": [
            {
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "The cat is black.\n"}},
                    ]
                }
            },
            {
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "猫は黒い"}},
                        {
                            "textRun": {
                                "content": "です\n",
                                "textStyle": {
                                    "foregroundColor": {
                                        "color": {
                                            "rgbColor": {
                                                "red": 0.8,
                                                "green": 0.1,
                                                "blue": 0.1,
                                            }
                                        }
                                    }
                                },
                            }
                        },
                    ]
                }
            },
        ]
    }
}


@pytest.fixture(autouse=True)
def _set_google_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", GOOGLE_CLIENT_SECRET)


def test_build_authorize_url_includes_scopes_and_state():
    url = google_docs.build_authorize_url(
        redirect_uri="https://example.com/callback", state="xyz"
    )

    assert url.startswith(google_docs.AUTH_BASE_URL)
    assert "client_id=test-client-id" in url
    assert "state=xyz" in url
    assert "documents.readonly" in url
    assert "access_type=offline" in url


@respx.mock
async def test_exchange_code_for_tokens():
    route = respx.post(google_docs.TOKEN_URL).mock(
        return_value=Response(
            200,
            json={
                "access_token": "at-123",
                "refresh_token": "rt-456",
                "expires_in": 3600,
            },
        )
    )

    tokens = await google_docs.exchange_code_for_tokens(
        code="auth-code", redirect_uri="https://example.com/callback"
    )

    assert tokens["access_token"] == "at-123"
    assert tokens["refresh_token"] == "rt-456"
    sent_body = route.calls.last.request.content.decode()
    assert "code=auth-code" in sent_body
    assert "grant_type=authorization_code" in sent_body


@respx.mock
async def test_refresh_access_token():
    respx.post(google_docs.TOKEN_URL).mock(
        return_value=Response(200, json={"access_token": "at-789", "expires_in": 3600})
    )

    tokens = await google_docs.refresh_access_token(refresh_token="rt-456")

    assert tokens["access_token"] == "at-789"


@respx.mock
async def test_fetch_document():
    document_id = "doc-abc"
    route = respx.get(f"{google_docs.DOCS_API_BASE_URL}/documents/{document_id}").mock(
        return_value=Response(200, json=DOC_FIXTURE)
    )

    result = await google_docs.fetch_document(document_id, access_token="at-123")

    assert result == DOC_FIXTURE
    assert route.calls.last.request.headers["Authorization"] == "Bearer at-123"


def test_flatten_runs_identifies_red_spans():
    spans = google_docs.flatten_runs(DOC_FIXTURE)

    assert spans == [
        {"text": "The cat is black.\n", "color": None},
        {"text": "猫は黒い", "color": None},
        {"text": "です\n", "color": "red"},
    ]


def test_flatten_runs_ignores_non_paragraph_elements():
    doc = {"body": {"content": [{"sectionBreak": {}}]}}

    assert google_docs.flatten_runs(doc) == []
