"""Tool schemas + dispatcher for the inner agent.

Wires the AnkiConnect, ElevenLabs, and Google Docs clients (tasks 3-5) as
Claude tool-use tools. `TOOL_SCHEMAS` is the `tools` list passed to the
Messages API; `dispatch_tool` executes a `tool_use` block's call against the
matching underlying client function.

Values the model should never be trusted to supply itself (the Google OAuth
access token) are passed into `dispatch_tool` as call-context, not read from
the model's tool input.
"""

import asyncio
import base64
import json
import mimetypes
import re
from collections.abc import Awaitable, Callable

from sqlmodel import Session

from app.agent import workflow_specs
from app.clients import ankiconnect, azure_tts, dictionary, elevenlabs, forvo, gemini_images, gemini_multimodal, google_docs, tatoeba, wikimedia_image_search
from app.models import AudioClip, ImageAsset, PendingCard, get_engine

# Magic-byte prefixes for the image formats a Wikimedia Commons search
# result (or an uploaded file) are realistically going to be.
# ImageAsset.content_type is required, but wikimedia_image_search.search_images
# only returns raw bytes (no per-result content-type is reliably available
# from the Commons search API response), so it's sniffed here instead of
# trusted from a header.
_IMAGE_MAGIC_BYTES: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),
]


def _validate_media_input(kind: str, value: dict | None, id_key: str) -> None:
    """The model occasionally sends `audio`/`picture` as something other than
    the object the tool schema declares (e.g. wrapping it in a list) — tool
    schemas aren't enforced server-side. Catching that here, right where the
    model's input is read, turns it into an immediate is_error tool result
    the model can see and self-correct from (see app.agent.core's dispatch_tool
    try/except), instead of the bad shape getting persisted onto a PendingCard
    and only surfacing as an opaque AnkiConnect failure much later when Dylan
    clicks "create" — see bug report #30."""

    if value is None:
        return
    if not isinstance(value, dict) or id_key not in value or "fields" not in value:
        raise ValueError(
            f"{kind} must be an object with '{id_key}' and 'fields' keys, "
            f"got {value!r}"
        )


def _guess_image_content_type(data: bytes) -> str:
    for magic, content_type in _IMAGE_MAGIC_BYTES:
        if data.startswith(magic):
            return content_type
    return "image/jpeg"


# Matches [[audio_clip_<id>]] / [[image_<id>]], with an optional decorative
# extension the model may add for readability (e.g. [[audio_clip_34.mp3]]),
# which is ignored — the id is what's actually looked up.
_MEDIA_PLACEHOLDER_RE = re.compile(r"\[\[(audio_clip|image)_(\d+)(?:\.\w+)?\]\]")


def _resolve_multimodal_prompt(prompt: str, session: Session) -> list[dict]:
    """Split `prompt` on [[audio_clip_<id>]]/[[image_<id>]] placeholders,
    resolving each against AudioClip/ImageAsset, into the ordered
    text/media part list gemini_multimodal.ask expects. Raises ValueError
    (surfaced to the model as an is_error tool_result — see app.agent.core)
    if a placeholder references an id that doesn't exist, so the model can
    see its mistake and retry with a real id instead of a clip silently
    failing later."""
    parts: list[dict] = []
    pos = 0
    for match in _MEDIA_PLACEHOLDER_RE.finditer(prompt):
        if match.start() > pos:
            parts.append({"text": prompt[pos : match.start()]})

        kind, id_str = match.group(1), int(match.group(2))
        if kind == "audio_clip":
            clip = session.get(AudioClip, id_str)
            if clip is None:
                raise ValueError(f"No audio clip with id {id_str}")
            parts.append({"data": clip.audio, "mime_type": "audio/mpeg"})
        else:
            image = session.get(ImageAsset, id_str)
            if image is None:
                raise ValueError(f"No image with id {id_str}")
            parts.append({"data": image.data, "mime_type": image.content_type})

        pos = match.end()

    if pos < len(prompt):
        parts.append({"text": prompt[pos:]})
    return parts


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
            "Generate audio options for a piece of Japanese text, so Dylan "
            "can pick the best-sounding take. Available in a male or female "
            "voice — pick whichever fits the card (e.g. the speaker in the "
            "lesson), or ask Dylan if it's not obvious which he wants. Two "
            "backends: \"elevenlabs\" (default) and \"azure\". ElevenLabs has "
            "no way to force Japanese pronunciation — it just reads whatever "
            "plain text you give it, so kanji misreadings are only avoidable "
            "by getting the reading right yourself beforehand. Azure instead "
            "takes a structural `segments` breakdown (surface text + kana "
            "reading per word) and speaks each word from its reading "
            "directly, which reliably avoids misreadings ElevenLabs is "
            "prone to — prefer azure with segments for any text containing "
            "kanji that has more than one plausible reading. Returns "
            "clip_ids (not the raw audio) — once Dylan picks one, pass its "
            "clip_id into create_anki_note's audio argument to actually "
            "attach it to the note; the clip is not saved anywhere on its "
            "own."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "The Japanese text to synthesize. Always required, even "
                        "when segments is given (used as the AudioClip's stored "
                        "text/label)."
                    ),
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
                "provider": {
                    "type": "string",
                    "enum": ["elevenlabs", "azure"],
                    "description": "Which TTS backend to use.",
                    "default": "elevenlabs",
                },
                "segments": {
                    "type": "array",
                    "description": (
                        "Only used when provider is \"azure\". Breaks `text` "
                        "into (surface text, kana reading) pairs so each "
                        "kanji-bearing word is spoken from its reading rather "
                        "than relying on the voice to read the kanji "
                        "correctly, e.g. [{\"text\": \"明日\", \"reading\": "
                        "\"あした\"}, {\"text\": \"行きます\"}] for 明日行きます. "
                        "Omit `reading` for segments that are already kana or "
                        "unambiguous."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "reading": {"type": "string"},
                        },
                        "required": ["text"],
                    },
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
            "Search Wikimedia Commons for candidate images matching a query "
            "(e.g. to illustrate a card), so Dylan can pick the best one — "
            "same choice-then-attach pattern as generate_audio. Good for "
            "well-known subjects (animals, places, historical/educational "
            "topics); less reliable for niche or branded content — "
            "generate_image may work better for those. Returns image_ids "
            "(not the raw images); once Dylan picks one, pass its image_id "
            "into create_anki_note's picture argument to attach it."
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
        "name": "search_example_sentences",
        "description": (
            "Search Tatoeba for real, native-written Japanese sentences with "
            "an English translation, so a card's example sentence can come "
            "from a real corpus instead of one the model invents. Returns "
            "each match's Japanese text, English translation (when "
            "available), and an audio_id when Tatoeba has native audio for "
            "that sentence — pass a chosen audio_id into create_anki_note's "
            "audio argument to attach it, same choice-then-attach pattern as "
            "generate_audio."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The Japanese search query, e.g. a word or phrase to find example sentences for.",
                },
                "n": {
                    "type": "integer",
                    "description": "Number of example sentences to find.",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_word_pronunciations",
        "description": (
            "Search Forvo for real native-speaker recordings of a Japanese "
            "word, sorted by vote/rating count, so a card's audio can come "
            "from a real speaker instead of ElevenLabs TTS when Dylan wants "
            "that. Returns clip_ids (not the raw audio) — once Dylan picks "
            "one, pass its clip_id into create_anki_note's audio argument to "
            "attach it, same choice-then-attach pattern as generate_audio."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "word": {
                    "type": "string",
                    "description": "The Japanese word to find pronunciations for.",
                },
                "n": {
                    "type": "integer",
                    "description": "Number of pronunciation options to find.",
                    "default": 3,
                },
            },
            "required": ["word"],
        },
    },
    {
        "name": "search_dictionary",
        "description": (
            "Look up a Japanese word in Jisho's dictionary, so definitions "
            "come from a real dictionary rather than the model's own "
            "knowledge. Returns each match's readings, English meanings, "
            "parts of speech, whether it's a common word, and a frequency "
            "score (wordfreq's zipf scale, roughly 0-8, higher is more "
            "frequent) to help judge whether a word is worth a card."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The Japanese word or phrase to look up.",
                },
                "n": {
                    "type": "integer",
                    "description": "Number of dictionary entries to return.",
                    "default": 3,
                },
            },
            "required": ["query"],
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
            "to handle a recurring source or card format — e.g. how a "
            "particular doc is laid out, how corrections are found, or how "
            "fields map onto a note type — so a future session can offer to "
            "reuse it instead of starting from scratch."
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
    {
        "name": "ask_multimodal_model",
        "description": (
            "Ask a multimodal model a question that can embed existing "
            "audio clips or images directly in the prompt, not just "
            "describe them in words — e.g. useful for comparing several "
            "generate_audio takes for naturalness/pronunciation and asking "
            "the model to pick a favorite, or for opinions on generated "
            "images. Not a fixed workflow — construct whatever prompt fits "
            "what's actually needed. Embed media by id using "
            "[[audio_clip_<id>]] for an AudioClip id (from generate_audio's "
            "clip_ids) or [[image_<id>]] for an ImageAsset id (from "
            "search_images/generate_image), inline wherever they're "
            "relevant in the prompt text, e.g. 'Option A: [[audio_clip_34]]"
            "\\nOption B: [[audio_clip_36]]\\nWhich sounds more natural for "
            "\"これはペンです\"?'. Returns the model's raw text reply — "
            "read it yourself and decide what to do with it (report back to "
            "Dylan, auto-pick between two close options, narrow candidates "
            "down before asking Dylan to choose, etc.) rather than assuming "
            "a fixed format."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "The question, with [[audio_clip_<id>]]/[[image_<id>]] "
                        "placeholders embedded wherever a clip/image belongs."
                    ),
                },
            },
            "required": ["prompt"],
        },
    },
]


async def _create_note_in_anki(
    deck_name: str,
    model_name: str,
    fields: dict[str, str],
    tags: list[str] | None,
    audio_input: dict | None,
    picture_input: dict | None,
) -> int:
    """Resolve a picked audio clip/image (if any) to AnkiConnect's media-
    attachment shape and actually call `ankiconnect.create_note`. Shared by
    `dispatch_tool`'s `create_anki_note` branch (when `instant_creation` is
    True) and `POST /api/pending-cards/{id}/create` (`app.api.chat`), so
    there's exactly one place that talks to AnkiConnect for note creation."""

    audio = None
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
        deck_name=deck_name,
        model_name=model_name,
        fields=fields,
        tags=tags,
        audio=audio,
        picture=picture,
    )
    # Fire-and-forget, not awaited: the note is already created at this
    # point, so a slow/failed sync shouldn't hold up the response to Dylan.
    # This matters more than it sounds — bug report #31 traced back to an
    # AnkiWeb sync attempt wedging Anki's single-threaded process for hours
    # (a known, previously-unresolved failure mode, see PROGRESS.md's
    # 2026-07-10 entry), which was otherwise stalling every single
    # note-creation request behind it. Anki's own periodic/on-open sync (or
    # a manual sync_anki call) will pick up the note later regardless if
    # this one fails or never returns.
    _fire_and_forget(_sync_best_effort())
    return note_id


# asyncio.create_task only holds a weak reference to the task, so without
# keeping one here a background sync could be garbage-collected mid-flight.
_background_sync_tasks: set[asyncio.Task] = set()


def _fire_and_forget(coro: Awaitable[None]) -> None:
    task = asyncio.create_task(coro)
    _background_sync_tasks.add(task)
    task.add_done_callback(_background_sync_tasks.discard)


async def _sync_best_effort() -> None:
    try:
        await ankiconnect.sync()
    except Exception:
        pass


async def dispatch_tool(
    name: str,
    tool_input: dict,
    *,
    get_access_token: Callable[[], Awaitable[str]] | None = None,
    instant_creation: bool = False,
) -> object:
    """Execute a tool_use call against the underlying client and return a
    JSON-serializable result to send back as the tool_result content.

    `instant_creation` controls what `create_anki_note` actually does: True
    calls AnkiConnect immediately (today's original behavior), False (the
    default) instead saves a `PendingCard` draft for Dylan to preview/create/
    discard via the `/api/pending-cards/*` endpoints (`app.api.chat`). It's
    call-context threaded down from the conversation's own setting, same as
    `get_access_token` — never read from the model's tool input."""

    if name == "fetch_google_doc":
        if get_access_token is None:
            raise ValueError("fetch_google_doc requires get_access_token")
        access_token = await get_access_token()
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
        provider = tool_input.get("provider", "elevenlabs")
        if provider == "azure":
            voice = tool_input.get("voice", azure_tts.DEFAULT_VOICE)
            options = await azure_tts.generate_audio_options(
                tool_input["text"], n=n, voice=voice, segments=tool_input.get("segments")
            )
        else:
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
        # `voice` is prefixed with the provider so it's visible which
        # backend produced a given clip without a schema/column change —
        # AudioClip.voice is a required str already (see app/models.py).
        engine = get_engine()
        clip_ids = []
        with Session(engine) as session:
            for option in options:
                clip = AudioClip(
                    text=tool_input["text"],
                    voice=f"{provider}:{voice}",
                    audio=option,
                    source="generate",
                )
                session.add(clip)
                session.commit()
                session.refresh(clip)
                clip_ids.append(clip.id)
        return {"clip_ids": clip_ids}

    if name == "create_anki_note":
        deck_name = tool_input["deck_name"]
        model_name = tool_input["model_name"]
        fields = tool_input["fields"]
        tags = tool_input.get("tags")
        _validate_media_input("audio", tool_input.get("audio"), "clip_id")
        _validate_media_input("picture", tool_input.get("picture"), "image_id")
        if instant_creation:
            note_id = await _create_note_in_anki(
                deck_name,
                model_name,
                fields,
                tags,
                tool_input.get("audio"),
                tool_input.get("picture"),
            )
            return {"note_id": note_id}

        # Draft-only: no AnkiConnect call at all. A picked audio clip/image
        # (if any) is stored on PendingCard so POST /api/pending-cards/{id}/
        # create (app.api.chat) can attach it once Dylan confirms the draft —
        # see task 60's PROGRESS.md entry for why this wasn't the case
        # originally.
        audio_input = tool_input.get("audio")
        picture_input = tool_input.get("picture")
        engine = get_engine()
        with Session(engine) as session:
            pending = PendingCard(
                deck_name=deck_name,
                model_name=model_name,
                fields=json.dumps(fields),
                tags=json.dumps(tags) if tags else None,
                audio=json.dumps(audio_input) if audio_input else None,
                picture=json.dumps(picture_input) if picture_input else None,
                status="pending",
            )
            session.add(pending)
            session.commit()
            session.refresh(pending)
            pending_card_id = pending.id
        return {"pending_card_id": pending_card_id, "status": "pending"}

    if name == "search_images":
        n = tool_input.get("n", 3)
        images = await wikimedia_image_search.search_images(tool_input["query"], n=n)
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

    if name == "search_example_sentences":
        n = tool_input.get("n", 5)
        sentences = await tatoeba.search_sentences(tool_input["query"], n=n)
        engine = get_engine()
        results = []
        with Session(engine) as session:
            for sentence in sentences:
                audio_id = None
                if sentence["audio"] is not None:
                    clip = AudioClip(
                        text=sentence["japanese"],
                        voice=sentence["audio_author"] or "native",
                        audio=sentence["audio"],
                        source="tatoeba",
                    )
                    session.add(clip)
                    session.commit()
                    session.refresh(clip)
                    audio_id = clip.id
                results.append(
                    {
                        "japanese": sentence["japanese"],
                        "english": sentence["english"],
                        "audio_id": audio_id,
                    }
                )
        return {"sentences": results}

    if name == "search_word_pronunciations":
        n = tool_input.get("n", 3)
        pronunciations = await forvo.search_pronunciations(tool_input["word"], n=n)
        engine = get_engine()
        clip_ids = []
        with Session(engine) as session:
            for pronunciation in pronunciations:
                clip = AudioClip(
                    text=tool_input["word"],
                    voice=pronunciation["username"] or "native",
                    audio=pronunciation["audio"],
                    source="forvo",
                )
                session.add(clip)
                session.commit()
                session.refresh(clip)
                clip_ids.append(clip.id)
        return {"clip_ids": clip_ids}

    if name == "search_dictionary":
        n = tool_input.get("n", 3)
        return {"results": await dictionary.search_words(tool_input["query"], n=n)}

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

    if name == "ask_multimodal_model":
        engine = get_engine()
        with Session(engine) as session:
            parts = _resolve_multimodal_prompt(tool_input["prompt"], session)
        response_text = await gemini_multimodal.ask(parts)
        return {"response": response_text}

    raise ValueError(f"Unknown tool: {name!r}")
