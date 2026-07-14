"""Renders Anki's card templates (qfmt/afmt + CSS) into preview HTML.

Only the subset of Anki's template syntax Dylan's real note types actually use
is supported: `{{FieldName}}` substitution, `{{FrontSide}}` (afmt only),
`{{#FieldName}}...{{/FieldName}}` / `{{^FieldName}}...{{/FieldName}}`
conditional sections, and `{{cloze:FieldName}}`. Exotic/malformed syntax is
left untouched in the output rather than raising — a broken-looking preview
beats a 500 on a real card the agent already drafted.

Cloze rendering always previews ordinal `c1` as the representative card, even
for a note whose field contains multiple cloze numbers (`{{c1::...}}
{{c2::...}}` in the same field) — matching real Anki's actual behavior for a
single rendered card: the active ordinal's text is masked (front) or revealed
(back) inside a `<span class="cloze">` (so the note type's own CSS `.cloze`
rule applies, same as a real Anki card), while every *other* ordinal in that
field is always shown revealed and unstyled on both sides.
"""

import re

_SECTION_RE = re.compile(r"\{\{([#^])([^{}]+?)\}\}(.*?)\{\{/\2\}\}", re.DOTALL)
_CLOZE_FIELD_RE = re.compile(r"\{\{cloze:([^{}]+?)\}\}")
_CLOZE_DELETION_RE = re.compile(r"\{\{c(\d+)::(.*?)\}\}", re.DOTALL)
_FIELD_RE = re.compile(r"\{\{([^#^/:{}]+?)\}\}")

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
