"""Gemini provider — translates to/from the Anthropic-shaped internal
representation `run_turn` and the rest of the codebase (persistence,
`_extract_payloads`, tests) already speak, so the tool-use loop in
`app/agent/core.py` doesn't need to know which provider answered.

Anthropic's `input_schema` (plain JSON Schema) is passed straight through as
Gemini's `parameters_json_schema` — no separate schema translation needed.
The real difference is message/response shape:
  - Anthropic tool_use/tool_result blocks pair by an opaque `id`; Gemini's
    FunctionCall/FunctionResponse pair by `name` (and, in this SDK version,
    also carry an `id` — used when present, synthesized otherwise so our
    internal `tool_use_id` bookkeeping always has something to key on).
  - Gemini only allows `role` "user"/"model" (no "assistant", no separate
    role for tool results) — tool_use blocks map to "model", tool_result
    blocks map to "user", same as plain text turns.
  - Gemini takes `system_instruction` as request config, not a content
    block.
"""

import json
import os
import uuid
from types import SimpleNamespace

from google import genai
from google.genai import types


def _client() -> genai.Client:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _block_type(block) -> str:
    return block["type"] if isinstance(block, dict) else block.type


def _block_get(block, key: str):
    return block[key] if isinstance(block, dict) else getattr(block, key)


def _collect_tool_use_names(messages: list[dict]) -> dict[str, str]:
    """Map tool_use_id -> tool name, so tool_result blocks (which only carry
    the id) can be translated into Gemini's name-keyed FunctionResponse."""

    names: dict[str, str] = {}
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            continue
        for block in content:
            if _block_type(block) == "tool_use":
                names[_block_get(block, "id")] = _block_get(block, "name")
    return names


def _to_gemini_contents(messages: list[dict]) -> list[types.Content]:
    tool_use_names = _collect_tool_use_names(messages)
    contents = []
    for message in messages:
        role = "model" if message["role"] == "assistant" else "user"
        content = message["content"]
        if isinstance(content, str):
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=content)]))
            continue

        parts = []
        for block in content:
            block_type = _block_type(block)
            if block_type == "text":
                parts.append(types.Part.from_text(text=_block_get(block, "text")))
            elif block_type == "tool_use":
                parts.append(
                    types.Part(
                        function_call=types.FunctionCall(
                            id=_block_get(block, "id"),
                            name=_block_get(block, "name"),
                            args=_block_get(block, "input"),
                        )
                    )
                )
            elif block_type == "tool_result":
                tool_use_id = _block_get(block, "tool_use_id")
                raw = _block_get(block, "content")
                try:
                    parsed = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    parsed = raw
                key = "error" if isinstance(block, dict) and block.get("is_error") else "result"
                payload = parsed if isinstance(parsed, dict) else {key: parsed}
                parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=tool_use_id,
                            name=tool_use_names.get(tool_use_id, tool_use_id),
                            response=payload,
                        )
                    )
                )
        if parts:
            contents.append(types.Content(role=role, parts=parts))
    return contents


def _to_internal_response(response: types.GenerateContentResponse) -> object:
    candidate = response.candidates[0] if response.candidates else None
    parts = candidate.content.parts if candidate and candidate.content else []

    blocks = []
    has_function_call = False
    for part in parts:
        if part.text:
            blocks.append(SimpleNamespace(type="text", text=part.text))
        elif part.function_call:
            has_function_call = True
            call_id = part.function_call.id or f"gemini_call_{uuid.uuid4().hex[:12]}"
            blocks.append(
                SimpleNamespace(
                    type="tool_use",
                    id=call_id,
                    name=part.function_call.name,
                    input=dict(part.function_call.args or {}),
                )
            )

    stop_reason = "tool_use" if has_function_call else "end_turn"
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


async def create_message(
    *, system: str, tools: list[dict], messages: list[dict], max_tokens: int, model_id: str
) -> object:
    client = _client()
    function_declarations = [
        types.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters_json_schema=tool["input_schema"],
        )
        for tool in tools
    ]
    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=[types.Tool(function_declarations=function_declarations)],
        max_output_tokens=max_tokens,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    response = await client.aio.models.generate_content(
        model=model_id, contents=_to_gemini_contents(messages), config=config
    )
    return _to_internal_response(response)
