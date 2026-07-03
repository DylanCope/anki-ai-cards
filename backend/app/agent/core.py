"""Agent core: drives the `anthropic` SDK's tool-use loop to completion.

`run_turn` is the entry point task 9's chat API will call: given the prior
conversation history and a new user message, it loops through Claude's
tool_use requests (dispatching each via `app.agent.tools.dispatch_tool`)
until Claude produces a final text reply.
"""

import json
import os

import anthropic

from app.agent import workflow_specs
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import TOOL_SCHEMAS, dispatch_tool

MODEL_ID = "claude-opus-4-8"
MAX_TOKENS = 4096

# Safety valve against a runaway tool-use loop (e.g. a tool that always
# triggers another tool call) — not expected to be hit in normal operation.
MAX_ITERATIONS = 10


def _get_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


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
        f"{known_specs}. Consider offering to reuse one of these (via "
        f"load_workflow_spec) before starting from scratch."
    )


async def run_turn(
    history: list[dict],
    message: str,
    *,
    access_token: str | None = None,
) -> dict:
    """Run one user turn to completion, returning the updated history and
    the assistant's final text reply.

    `access_token` is the caller's Google OAuth access token, threaded
    through to tools (like `fetch_google_doc`) that need it — it is never
    read from the model's tool input.
    """

    client = _get_client()
    system_prompt = _build_system_prompt(history)
    messages: list[dict] = [*history, {"role": "user", "content": message}]

    for _ in range(MAX_ITERATIONS):
        response = await client.messages.create(
            model=MODEL_ID,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            tools=TOOL_SCHEMAS,
            messages=messages,
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
            result = await dispatch_tool(
                block.name, block.input, access_token=access_token
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError("Tool-use loop did not complete within MAX_ITERATIONS")
