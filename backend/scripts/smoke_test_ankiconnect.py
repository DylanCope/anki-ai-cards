"""Smoke test: confirm an AnkiConnect instance is reachable and responsive.

Calls the `version` action against a configurable URL and prints the
protocol version AnkiConnect reports. Intended for a human to run by hand
against the real deployed headless Anki app after the one-time manual VNC
login to AnkiWeb (see AGENTS.md) — not part of the automated test suite,
though `tests/test_smoke_test_ankiconnect.py` exercises it against a mocked
AnkiConnect server.

Usage:
    uv run python -m scripts.smoke_test_ankiconnect --url http://localhost:8765
    uv run python -m scripts.smoke_test_ankiconnect  # uses $ANKICONNECT_URL
"""

import argparse
import asyncio
import os
import sys

from app.clients import ankiconnect


async def check_ankiconnect(url: str) -> object:
    """Return AnkiConnect's reported protocol version, or raise on failure."""
    return await ankiconnect.invoke("version", base_url=url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("ANKICONNECT_URL"),
        help="AnkiConnect base URL (defaults to $ANKICONNECT_URL)",
    )
    args = parser.parse_args(argv)

    if not args.url:
        print("error: no --url given and $ANKICONNECT_URL is unset", file=sys.stderr)
        return 1

    try:
        version = asyncio.run(check_ankiconnect(args.url))
    except Exception as exc:  # noqa: BLE001 - report any failure to the caller
        print(f"error: AnkiConnect at {args.url!r} is not reachable: {exc}", file=sys.stderr)
        return 1

    print(f"ok: AnkiConnect at {args.url!r} responded with protocol version {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
