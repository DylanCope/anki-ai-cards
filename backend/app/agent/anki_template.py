"""Renders Anki's card templates (qfmt/afmt + CSS) into preview HTML.

Only the subset of Anki's template syntax Dylan's real note types actually use
is supported: `{{FieldName}}` substitution, `{{FrontSide}}` (afmt only),
`{{#FieldName}}...{{/FieldName}}` / `{{^FieldName}}...{{/FieldName}}`
conditional sections, and `{{cloze:FieldName}}`. Any other `{{filter:Field}}`
form (Anki has several built-ins — `furigana:`, `kanji:`, `kana:`, `hint:`,
`type:`, `tts:` — and third-party note types add their own, e.g. Dylan's
Migaku note type's `{{editable:Field}}`) falls back to plain field-value
substitution, ignoring the filter's real rendering behavior. Confirmed
against Dylan's real "Migaku Japanese Custom" note type (via live AnkiConnect
data) that without this fallback, `{{editable:Field}}` was left completely
unsubstituted in the output — every real field (sentence, word, definitions,
audio, images) was invisible, just literal `{{editable:...}}` text, which is
worse than an imperfect-but-legible best-effort render. Exotic/malformed
syntax beyond this is left untouched in the output rather than raising — a
broken-looking preview beats a 500 on a real card the agent already drafted.

Cloze rendering always previews ordinal `c1` as the representative card, even
for a note whose field contains multiple cloze numbers (`{{c1::...}}
{{c2::...}}` in the same field) — matching real Anki's actual behavior for a
single rendered card: the active ordinal's text is masked (front) or revealed
(back) inside a `<span class="cloze">` (so the note type's own CSS `.cloze`
rule applies, same as a real Anki card), while every *other* ordinal in that
field is always shown revealed and unstyled on both sides.

`find_local_media_refs`/`inline_local_media` are a separate concern from
template rendering proper: some note types' CSS/HTML reference local Anki
collection.media files by bare filename (a custom @font-face, an `<img>` in
the template itself, not a picked/attached asset) — confirmed against
Dylan's real "Migaku Japanese Custom" note type, which loads a custom font
this way. The preview iframe has no way to resolve a bare filename, so
`app.api.chat`'s preview endpoint fetches these via AnkiConnect's
`retrieveMediaFile` and inlines them as data URIs using the two functions
below. Kept as pure functions here (no AnkiConnect/network dependency, same
rationale as `render_card` itself) — the actual fetching is the API layer's
job.
"""

import re

_SECTION_RE = re.compile(r"\{\{([#^])([^{}]+?)\}\}(.*?)\{\{/\2\}\}", re.DOTALL)
_CLOZE_FIELD_RE = re.compile(r"\{\{cloze:([^{}]+?)\}\}")
_CLOZE_DELETION_RE = re.compile(r"\{\{c(\d+)::(.*?)\}\}", re.DOTALL)
_FIELD_RE = re.compile(r"\{\{([^#^/:{}]+?)\}\}")
# Any remaining `{{filter:Field}}` once `{{cloze:...}}` has already been
# resolved above — see module docstring for why this falls back to a plain
# field substitution instead of leaving the token unrendered.
_FILTERED_FIELD_RE = re.compile(r"\{\{[a-zA-Z0-9_-]+:([^{}]+?)\}\}")

PREVIEW_CLOZE_ORDINAL = 1


def _process_sections(template: str, fields: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        kind, name, inner = match.group(1), match.group(2).strip(), match.group(3)
        non_empty = bool(fields.get(name, "").strip())
        show = non_empty if kind == "#" else not non_empty
        return inner if show else ""

    result = template
    previous = None
    # Sections aren't nested in Dylan's real templates, so a fixed-point loop
    # (rather than a real recursive-descent parser) is enough to resolve
    # multiple sequential/sibling sections in one template.
    while previous != result:
        previous = result
        result = _SECTION_RE.sub(repl, result)
    return result


def _render_cloze_deletion(value: str, ordinal: int, side: str) -> str:
    def repl(match: re.Match[str]) -> str:
        num = int(match.group(1))
        inner = match.group(2)
        text, _, hint = inner.partition("::")
        if num != ordinal:
            return text
        if side == "front":
            shown = f"[{hint}]" if hint else "[...]"
        else:
            shown = text
        return f'<span class="cloze">{shown}</span>'

    return _CLOZE_DELETION_RE.sub(repl, value)


def _process_cloze(template: str, fields: dict[str, str], *, side: str, ordinal: int) -> str:
    def repl(match: re.Match[str]) -> str:
        field_name = match.group(1).strip()
        return _render_cloze_deletion(fields.get(field_name, ""), ordinal, side)

    return _CLOZE_FIELD_RE.sub(repl, template)


def _render_template(
    template: str,
    fields: dict[str, str],
    *,
    side: str,
    ordinal: int,
    front_html: str | None = None,
) -> str:
    result = _process_sections(template, fields)
    result = _process_cloze(result, fields, side=side, ordinal=ordinal)
    if front_html is not None:
        result = result.replace("{{FrontSide}}", front_html)
    result = _FILTERED_FIELD_RE.sub(lambda m: fields.get(m.group(1).strip(), ""), result)
    result = _FIELD_RE.sub(lambda m: fields.get(m.group(1).strip(), ""), result)
    return result


def render_card(qfmt: str, afmt: str, css: str, fields: dict[str, str]) -> dict:
    try:
        front_html = _render_template(qfmt, fields, side="front", ordinal=PREVIEW_CLOZE_ORDINAL)
        back_html = _render_template(
            afmt,
            fields,
            side="back",
            ordinal=PREVIEW_CLOZE_ORDINAL,
            front_html=front_html,
        )
    except Exception:
        # Best-effort fallback for template syntax we don't understand — an
        # unrendered-looking preview beats a 500 on a card the agent already
        # drafted.
        front_html = qfmt
        back_html = afmt.replace("{{FrontSide}}", front_html)

    return {"front_html": front_html, "back_html": back_html, "css": css}


_CSS_URL_RE = re.compile(r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""")
_IMG_SRC_RE = re.compile(r"""<img\b[^>]*\bsrc=["']([^"']+)["']""", re.IGNORECASE)


def _is_local_media_ref(ref: str) -> bool:
    return not ref.startswith(("http://", "https://", "data:", "//", "#"))


def find_local_media_refs(css: str, front_html: str, back_html: str) -> set[str]:
    """Local (Anki collection.media) filenames referenced by a rendered
    card's CSS `url(...)` or HTML `<img src="...">` — anything not already
    an absolute URL or data URI."""

    refs: set[str] = set()
    refs.update(ref for ref in _CSS_URL_RE.findall(css) if _is_local_media_ref(ref))
    for html in (front_html, back_html):
        refs.update(ref for ref in _IMG_SRC_RE.findall(html) if _is_local_media_ref(ref))
    return refs


def inline_local_media(
    css: str, front_html: str, back_html: str, media_data_uris: dict[str, str]
) -> dict[str, str]:
    """Replace local media filename references with their data-URI
    equivalents from `media_data_uris` (filename -> `"data:<mime>;base64,
    <bytes>"`). Substitution is scoped to each matched `url(...)`/`src="..."`
    span rather than a blind string replace, so a filename that happens to
    be a substring of unrelated text elsewhere is never touched."""

    def _sub(pattern: re.Pattern[str], text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            ref = match.group(1)
            data_uri = media_data_uris.get(ref)
            return match.group(0).replace(ref, data_uri) if data_uri else match.group(0)

        return pattern.sub(repl, text)

    return {
        "css": _sub(_CSS_URL_RE, css),
        "front_html": _sub(_IMG_SRC_RE, front_html),
        "back_html": _sub(_IMG_SRC_RE, back_html),
    }
