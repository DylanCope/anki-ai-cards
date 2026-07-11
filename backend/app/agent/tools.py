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
import mimetypes

from sqlmodel import Session

from app.agent import workflow_specs
from app.clients import ankiconnect, elevenlabs, gemini_images, google_docs, google_image_search
from app.models import AudioClip, ImageAsset, get_engine

# Magic-byte prefixes for the image formats Google Image Search results (or
# an uploaded file) are realistically going to be. ImageAsset.content_type
# is required, but google_image_search.search_images only returns raw bytes
# (no per-result content-type is reliably available from the Custom Search
# API response), so it's sniffed here instead of trusted from a header.
_IMAGE_MAGIC_BYTES: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),
]


def _guess_image_content_type(data: bytes) -> str:
    for magic, content_type in _IMAGE_MAGIC_BYTES:
        if data.startswith(magic):
            return content_type
    return "image/jpeg"

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
        "description": (
            "Generate audio options for a piece of Japanese text via ElevenLabs, "
            "so Dylan can pick the best-sounding take. Available in a male or "
            "female voice — pick whichever fits the card (e.g. the speaker in "
            "the lesson), or ask Dylan if it's not obvious which he wants. "
            "Returns clip_ids (not the raw audio) — once Dylan picks one, pass "
            "its clip_id into create_anki_note's audio argument to actually "
            "attach it to the note; the clip is not saved anywhere on its own."
        ),
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
                "voice": {
                    "type": "string",
                    "enum": ["male", "female"],
                    "description": "Which voice to use.",
                    "default": "male",
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
                "audio": {
                    "type": "object",
                    "description": (
                        "Attach a previously generated audio clip (a clip_id "
                        "from generate_audio's result, after Dylan picked an "
                        "option) to this note. AnkiConnect stores the audio in "
                        "Anki's media collection and appends the [sound:...] "
                        "reference to each listed field itself."
                    ),
                    "properties": {
                        "clip_id": {
                            "type": "integer",
                            "description": "A clip_id from generate_audio's result.",
                        },
                        "fields": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Field name(s) to attach the audio to, e.g. the "
                                "discovered audio field for this note type."
                            ),
                        },
                    },
                    "required": ["clip_id", "fields"],
                },
                "picture": {
                    "type": "object",
                    "description": (
                        "Attach a previously stored image (an image_id from an "
                        "uploaded, searched, or generated image, after Dylan "
                        "picked one) to this note. AnkiConnect stores the image "
                        "in Anki's media collection and appends an <img> "
                        "reference to each listed field itself."
                    ),
                    "properties": {
                        "image_id": {
                            "type": "integer",
                            "description": "An image_id referencing a stored image.",
                        },
                        "fields": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Field name(s) to attach the image to, e.g. the "
                                "discovered image field for this note type."
                            ),
                        },
                    },
                    "required": ["image_id", "fields"],
                },
            },
            "required": ["deck_name", "model_name", "fields"],
        },
    },
    {
        "name": "search_images",
        "description": (
            "Search the web for candidate images matching a query (e.g. to "
            "illustrate a card), so Dylan can pick the best one — same "
            "choice-then-attach pattern as generate_audio. Returns "
            "image_ids (not the raw images); once Dylan picks one, pass its "
            "image_id into create_anki_note's picture argument to attach it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The image search query.",
                },
                "n": {
                    "type": "integer",
                    "description": "Number of image options to find.",
                    "default": 3,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "generate_image",
        "description": (
            "Generate candidate images for a card from a text prompt via "
            "Gemini, so Dylan can pick the best one — same choice-then-attach "
            "pattern as generate_audio and search_images. Returns image_ids "
            "(not the raw images); once Dylan picks one, pass its image_id "
            "into create_anki_note's picture argument to attach it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The image generation prompt.",
                },
                "n": {
                    "type": "integer",
                    "description": "Number of image options to generate.",
                    "default": 3,
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "sync_anki",
        "description": "Trigger an AnkiConnect sync so newly created notes reach AnkiWeb, and from there Dylan's phone/desktop.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "save_workflow_spec",
        "description": (
            "Save (or update) a named, reusable workflow spec describing how "
            "to handle a source — e.g. how the lesson doc is laid out, how "
            "corrections are found, and how fields map onto the note type — "
            "so a future session can offer to reuse it instead of starting "
            "from scratch."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "A short, memorable name for this workflow spec.",
                },
                "spec": {
                    "type": "string",
                    "description": "The workflow spec content, describing how to handle this source.",
                },
            },
            "required": ["name", "spec"],
        },
    },
    {
        "name": "load_workflow_spec",
        "description": "Load a previously saved workflow spec by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The workflow spec's name, from list_workflow_specs.",
                }
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_workflow_specs",
        "description": "List the names of all saved workflow specs, so the agent can offer to reuse one.",
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
        voice = tool_input.get("voice", elevenlabs.DEFAULT_VOICE)
        options = await elevenlabs.generate_audio_options(
            tool_input["text"], n=n, voice=voice
        )
        # Persist the raw audio server-side and hand the model back only
        # small integer ids — not the audio itself. The model can't and
        # shouldn't reproduce large binary blobs in a later tool call; it
        # only needs a stable reference to pass into create_anki_note once
        # Dylan picks one. (This also avoids repeatedly re-sending tens of
        # KB of base64 per clip on every subsequent turn of the conversation.)
        engine = get_engine()
        clip_ids = []
        with Session(engine) as session:
            for option in options:
                clip = AudioClip(text=tool_input["text"], voice=voice, audio=option)
                session.add(clip)
                session.commit()
                session.refresh(clip)
                clip_ids.append(clip.id)
        return {"clip_ids": clip_ids}

    if name == "create_anki_note":
        audio = None
        audio_input = tool_input.get("audio")
        if audio_input:
            engine = get_engine()
            with Session(engine) as session:
                clip = session.get(AudioClip, audio_input["clip_id"])
            if clip is None:
                raise ValueError(f"Unknown audio clip_id: {audio_input['clip_id']!r}")
            audio = {
                "data": base64.b64encode(clip.audio).decode("ascii"),
                "filename": f"anki-ai-cards-{clip.id}.mp3",
                "fields": audio_input["fields"],
            }
        picture = None
        picture_input = tool_input.get("picture")
        if picture_input:
            engine = get_engine()
            with Session(engine) as session:
                image = session.get(ImageAsset, picture_input["image_id"])
            if image is None:
                raise ValueError(f"Unknown image image_id: {picture_input['image_id']!r}")
            extension = mimetypes.guess_extension(image.content_type) or ".jpg"
            picture = {
                "data": base64.b64encode(image.data).decode("ascii"),
                "filename": f"anki-ai-cards-{image.id}{extension}",
                "fields": picture_input["fields"],
            }
        note_id = await ankiconnect.create_note(
            deck_name=tool_input["deck_name"],
            model_name=tool_input["model_name"],
            fields=tool_input["fields"],
            tags=tool_input.get("tags"),
            audio=audio,
            picture=picture,
        )
        return {"note_id": note_id}

    if name == "search_images":
        n = tool_input.get("n", 3)
        images = await google_image_search.search_images(tool_input["query"], n=n)
        engine = get_engine()
        image_ids = []
        with Session(engine) as session:
            for data in images:
                image = ImageAsset(
                    content_type=_guess_image_content_type(data),
                    data=data,
                    source="search",
                )
                session.add(image)
                session.commit()
                session.refresh(image)
                image_ids.append(image.id)
        return {"image_ids": image_ids}

    if name == "generate_image":
        n = tool_input.get("n", 3)
        images = await gemini_images.generate_images(tool_input["prompt"], n=n)
        engine = get_engine()
        image_ids = []
        with Session(engine) as session:
            for data in images:
                image = ImageAsset(
                    content_type=_guess_image_content_type(data),
                    data=data,
                    source="generate",
                )
                session.add(image)
                session.commit()
                session.refresh(image)
                image_ids.append(image.id)
        return {"image_ids": image_ids}

    if name == "sync_anki":
        await ankiconnect.sync()
        return {"synced": True}

    if name == "save_workflow_spec":
        saved = workflow_specs.save_workflow_spec(
            tool_input["name"], tool_input["spec"]
        )
        return {"name": saved.name, "spec": saved.spec}

    if name == "load_workflow_spec":
        loaded = workflow_specs.load_workflow_spec(tool_input["name"])
        if loaded is None:
            return None
        return {"name": loaded.name, "spec": loaded.spec}

    if name == "list_workflow_specs":
        return [spec.name for spec in workflow_specs.list_workflow_specs()]

    raise ValueError(f"Unknown tool: {name!r}")
