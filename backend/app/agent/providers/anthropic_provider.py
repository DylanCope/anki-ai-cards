"""Anthropic Messages API provider.

Returns the SDK's response object as-is — `run_turn`'s loop already consumes
it directly (`response.content` blocks with `.type`/`.text`/`.name`/`.input`/
`.id`, `response.stop_reason`), so this is the reference shape every other
provider adapter normalizes into.
"""

import os

import anthropic


def _client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


async def create_message(
    *, system: str, tools: list[dict], messages: list[dict], max_tokens: int, model_id: str
) -> object:
    client = _client()
    return await client.messages.create(
        model=model_id,
        max_tokens=max_tokens,
        system=system,
        tools=tools,
        messages=messages,
    )
