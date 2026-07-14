"""Agent core: drives the tool-use loop to completion against whichever
model provider the conversation is set to.

`run_turn` is the entry point the chat API calls: given the prior
conversation history and a new user message, it loops through tool_use
requests (dispatching each via `app.agent.tools.dispatch_tool`) until the
model produces a final text reply. The loop itself is provider-agnostic —
each provider adapter in `app.agent.providers` normalizes its response into
the same Anthropic-shaped `{content: [...], stop_reason: ...}` object, since
that's also what gets persisted and re-parsed by `app.api.chat`.
"""

import json
from collections.abc import Awaitable, Callable

from app.agent import workflow_specs
from app.agent.model_registry import get_model
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.providers import anthropic_provider, gemini_provider
from app.agent.tools import TOOL_SCHEMAS, dispatch_tool

MAX_TOKENS = 4096

# Safety valve against a runaway tool-use loop (e.g. a tool that always
# triggers another tool call) — not expected to be hit in normal operation.
MAX_ITERATIONS = 10

_PROVIDER_MODULES = {
    "anthropic": anthropic_provider,
    "gemini": gemini_provider,
}


def _build_system_prompt(history: list[dict]) -> str:
    """Append known workflow-spec names to the system prompt at the start of
    a conversation (empty `history`), so the agent can offer to reuse one
    without having to call list_workflow_specs itself on every fresh chat."""

    if history:
        return SYSTEM_PROMPT

    names = [spec.name for spec in workflow_specs.list_workflow_specs()]
    if not names:
        return SYSTEM_PROMPT

    known_specs = ", ".join(names)
    return (
        f"{SYSTEM_PROMPT}\n\nKnown workflow specs from past sessions: "
        f"{known_specs}. Per the workflow-spec guidance above, check whether "
        f"one of these matches before starting from scratch on a card "
        f"creation request."
    )


async def run_turn(
    history: list[dict],
    message: str,
    *,
    get_access_token: Callable[[], Awaitable[str]] | None = None,
    model_id: str,
    instant_creation: bool = False,
) -> dict:
    """Run one user turn to completion, returning the updated history and
    the assistant's final text reply.

    `get_access_token` lazily resolves the caller's Google OAuth access
    token (refreshing it if needed) — threaded through to tools (like
    `fetch_google_doc`) that need it, and only called if one of them is
    actually invoked this turn, so a turn that never touches Google Docs
    never pays for (or can fail on) a token refresh. It is never read from
    the model's tool input. `model_id` selects which model (and therefore
    which provider adapter) drives this turn — see `app.agent.model_registry`.
    `instant_creation` mirrors the conversation's own setting and is passed
    straight through to every `dispatch_tool` call this turn (see that
    function's docstring for what it controls on `create_anki_note`).
    """

    provider_module = _PROVIDER_MODULES[get_model(model_id).provider]
    system_prompt = _build_system_prompt(history)
    messages: list[dict] = [*history, {"role": "user", "content": message}]

    for _ in range(MAX_ITERATIONS):
        response = await provider_module.create_message(
            system=system_prompt,
            tools=TOOL_SCHEMAS,
            messages=messages,
            max_tokens=MAX_TOKENS,
            model_id=model_id,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            reply = "".join(
                block.text for block in response.content if block.type == "text"
            )
            return {"history": messages, "reply": reply}

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                result = await dispatch_tool(
                    block.name,
                    block.input,
                    get_access_token=get_access_token,
                    instant_creation=instant_creation,
                )
            except Exception as exc:
                # Surface the failure back to the model as an error tool_result
                # instead of letting it crash the whole turn — Claude can then
                # explain what went wrong (and optionally retry/ask Dylan)
                # rather than the chat API hard-failing with no assistant
                # reply at all.
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"{block.name} failed: {exc}",
                        "is_error": True,
                    }
                )
                continue
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError("Tool-use loop did not complete within MAX_ITERATIONS")
