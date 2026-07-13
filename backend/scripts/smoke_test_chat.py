"""Smoke test: confirm the deployed chat agent can reach AnkiConnect end to end.

Sends a chat message asking the agent to list Anki note types and prints the
reply. Requires `DEV_API_KEY` to be set to the same value as the backend's
`DEV_API_KEY` secret (see AGENTS.md) — authenticates via the bearer-token
bypass `app.auth.require_auth` accepts instead of a browser session cookie.
Intended for a human or the Ralph loop to run by hand against the real
deployed backend, not part of the automated test suite (it makes a real
network call).

Usage:
    DEV_API_KEY=... uv run python -m scripts.smoke_test_chat
    DEV_API_KEY=... uv run python -m scripts.smoke_test_chat --url https://anki-ai-cards-backend.fly.dev
    DEV_API_KEY=... uv run python -m scripts.smoke_test_chat --conversation-id 3 --message "continue"

Chats belong to a conversation (see PROGRESS.md's 2026-07-10 "new chat/chat
history" entry) — with no `--conversation-id`, this creates a fresh one each
run via `POST /api/conversations`, so a rerun never lands in the same
conversation as a prior one. Pass `--conversation-id` explicitly to continue
an existing one instead.
"""

import argparse
import os
import sys

import httpx


def create_conversation(url: str, dev_api_key: str) -> int:
    response = httpx.post(
        f"{url.rstrip('/')}/api/conversations",
        headers={"Authorization": f"Bearer {dev_api_key}"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["id"]


def send_chat_message(url: str, conversation_id: int, message: str, dev_api_key: str) -> str:
    """POST `message` to `url`/api/chat and return the agent's reply text."""
    response = httpx.post(
        f"{url.rstrip('/')}/api/chat",
        json={"conversation_id": conversation_id, "message": message},
        headers={"Authorization": f"Bearer {dev_api_key}"},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["reply"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("BACKEND_PUBLIC_URL", "https://anki-ai-cards-backend.fly.dev"),
        help="Backend base URL (defaults to $BACKEND_PUBLIC_URL or the production backend)",
    )
    parser.add_argument(
        "--message",
        default="List my Anki note types.",
        help="Chat message to send",
    )
    parser.add_argument(
        "--conversation-id",
        type=int,
        default=None,
        help="Continue an existing conversation instead of creating a new one",
    )
    args = parser.parse_args(argv)

    dev_key = os.environ.get("DEV_API_KEY")
    if not dev_key:
        print("error: $DEV_API_KEY is unset", file=sys.stderr)
        return 1

    try:
        conversation_id = args.conversation_id or create_conversation(args.url, dev_key)
        reply = send_chat_message(args.url, conversation_id, args.message, dev_key)
    except httpx.HTTPStatusError as exc:
        print(f"error: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"error: request to {args.url!r} failed: {exc}", file=sys.stderr)
        return 1

    print(f"ok (conversation_id={conversation_id}): agent replied:\n{reply}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
