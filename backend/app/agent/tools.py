"""Tool schemas + dispatcher for the inner agent.

Wires the AnkiConnect, ElevenLabs, and Google Docs clients (tasks 3-5) as
Claude tool-use tools. `TOOL_SCHEMAS` is the `tools` list passed to the
Messages API; `dispatch_tool` executes a `tool_use` block's call against the
matching underlying client function.

Values the model should never be trusted to supply itself (the Google OAuth
access token) are passed into `dispatch_tool` as call-context, not read from
the model's tool input.
"""

import base64

from app.clients import ankiconnect, elevenlabs, google_docs

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "fetch_google_doc",
        "description": (
            "Fetch the lesson Google Doc and return it as a flat list of "
            "{text, color} spans in document order, so the freeform layout "
            "(English phrase / Dylan's attempt / teacher's correction) can "
            "be read directly. Spans with color 'red' are the teacher's "
            "marked corrections."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "description": "The Google Doc's document ID.",
                }
            },
            "required": ["document_id"],
        },
    },
    {
        "name": "list_anki_note_types",
        "description": "List the names of all note types (models) defined in Dylan's Anki collection.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_anki_note_type_fields",
        "description": "Get the field names for a given Anki note type, so field mapping is discovered live rather than assumed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_type": {
                    "type": "string",
                    "description": "The note type (model) name, from list_anki_note_types.",
                }
            },
            "required": ["note_type"],
        },
    },
    {
        "name": "generate_audio",
        "description": "Generate audio options for a piece of Japanese text via ElevenLabs, so Dylan can pick the best-sounding take.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The Japanese text to synthesize.",
                },
                "n": {
                    "type": "integer",
                    "description": "Number of audio options to generate.",
                    "default": 3,
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "create_anki_note",
        "description": "Create a new note in Dylan's Anki collection, using field names discovered via get_anki_note_type_fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deck_name": {"type": "string"},
                "model_name": {
                    "type": "string",
                    "description": "The note type name, from list_anki_note_types.",
                },
                "fields": {
                    "type": "object",
                    "description": "Mapping of field name to field content.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["deck_name", "model_name", "fields"],
        },
    },
    {
        "name": "sync_anki",
        "description": "Trigger an AnkiConnect sync so newly created notes reach AnkiWeb, and from there Dylan's phone/desktop.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


async def dispatch_tool(
    name: str, tool_input: dict, *, access_token: str | None = None
) -> object:
    """Execute a tool_use call against the underlying client and return a
    JSON-serializable result to send back as the tool_result content."""

    if name == "fetch_google_doc":
        if not access_token:
            raise ValueError("fetch_google_doc requires an access_token")
        doc_json = await google_docs.fetch_document(
            tool_input["document_id"], access_token
        )
        return google_docs.flatten_runs(doc_json)

    if name == "list_anki_note_types":
        return await ankiconnect.list_note_type_names()

    if name == "get_anki_note_type_fields":
        return await ankiconnect.get_note_type_fields(tool_input["note_type"])

    if name == "generate_audio":
        n = tool_input.get("n", 3)
        options = await elevenlabs.generate_audio_options(tool_input["text"], n=n)
        return [base64.b64encode(option).decode("ascii") for option in options]

    if name == "create_anki_note":
        note_id = await ankiconnect.create_note(
            deck_name=tool_input["deck_name"],
            model_name=tool_input["model_name"],
            fields=tool_input["fields"],
            tags=tool_input.get("tags"),
        )
        return {"note_id": note_id}

    if name == "sync_anki":
        await ankiconnect.sync()
        return {"synced": True}

    raise ValueError(f"Unknown tool: {name!r}")
