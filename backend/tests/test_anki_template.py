from app.agent.anki_template import (
    _sound_play_button,
    find_local_media_refs,
    inline_local_media,
    render_card,
)


def test_plain_field_substitution():
    result = render_card(
        qfmt="{{Front}}",
        afmt="{{Front}}<hr>{{Back}}",
        css=".card { font-family: arial; }",
        fields={"Front": "こんにちは", "Back": "hello"},
    )

    assert result["front_html"] == "こんにちは"
    assert result["back_html"] == "こんにちは<hr>hello"
    assert result["css"] == ".card { font-family: arial; }"


def test_conditional_section_shown_when_field_non_empty():
    template = "{{#Extra}}Note: {{Extra}}{{/Extra}}"

    result = render_card(
        qfmt=template,
        afmt=template,
        css="",
        fields={"Extra": "some context"},
    )

    assert result["front_html"] == "Note: some context"


def test_conditional_section_hidden_when_field_empty():
    template = "{{#Extra}}Note: {{Extra}}{{/Extra}}"

    result = render_card(
        qfmt=template,
        afmt=template,
        css="",
        fields={"Extra": ""},
    )

    assert result["front_html"] == ""


def test_inverted_section_shown_when_field_empty():
    template = "{{^Extra}}(no extra info){{/Extra}}"

    result = render_card(
        qfmt=template,
        afmt=template,
        css="",
        fields={"Extra": ""},
    )

    assert result["front_html"] == "(no extra info)"


def test_inverted_section_hidden_when_field_non_empty():
    template = "{{^Extra}}(no extra info){{/Extra}}"

    result = render_card(
        qfmt=template,
        afmt=template,
        css="",
        fields={"Extra": "some context"},
    )

    assert result["front_html"] == ""


def test_front_side_substitution_on_back_template():
    result = render_card(
        qfmt="{{Front}}",
        afmt="{{FrontSide}}<hr id=answer>{{Back}}",
        css="",
        fields={"Front": "question", "Back": "answer"},
    )

    assert result["back_html"] == "question<hr id=answer>answer"


def test_single_cloze_front_masks_and_back_reveals():
    result = render_card(
        qfmt="{{cloze:Text}}",
        afmt="{{cloze:Text}}<br>{{Extra}}",
        css="",
        fields={"Text": "食べる is {{c1::to eat}}", "Extra": "verb"},
    )

    assert result["front_html"] == '食べる is <span class="cloze">[...]</span>'
    assert result["back_html"] == (
        '食べる is <span class="cloze">to eat</span><br>verb'
    )


def test_cloze_with_hint_shows_hint_on_front():
    result = render_card(
        qfmt="{{cloze:Text}}",
        afmt="{{cloze:Text}}",
        css="",
        fields={"Text": "{{c1::to eat::verb hint}}"},
    )

    assert result["front_html"] == '<span class="cloze">[verb hint]</span>'
    assert result["back_html"] == '<span class="cloze">to eat</span>'


def test_multi_cloze_in_one_field_only_masks_the_previewed_ordinal():
    result = render_card(
        qfmt="{{cloze:Text}}",
        afmt="{{cloze:Text}}",
        css="",
        fields={"Text": "{{c1::to eat}} is {{c2::taberu}}"},
    )

    assert result["front_html"] == '<span class="cloze">[...]</span> is taberu'
    assert result["back_html"] == '<span class="cloze">to eat</span> is taberu'


def test_unknown_filter_falls_back_to_plain_field_substitution():
    # Anki has several built-in filters (furigana:, kanji:, kana:, hint:,
    # type:, tts:) and third-party note types add their own (e.g. Dylan's
    # Migaku note type's {{editable:Field}}) — none render the filter's real
    # behavior, but the field's raw value should still show up rather than
    # leaving the literal `{{filter:Field}}` token in the output.
    result = render_card(
        qfmt='<div>{{editable:Target Word}}</div>',
        afmt="{{furigana:Sentence}}",
        css="",
        fields={"Target Word": "誘惑[ゆうわく]", "Sentence": "彼は誘惑に負けた。"},
    )

    assert result["front_html"] == "<div>誘惑[ゆうわく]</div>"
    assert result["back_html"] == "彼は誘惑に負けた。"


def test_unknown_filter_does_not_interfere_with_cloze():
    result = render_card(
        qfmt="{{cloze:Text}}",
        afmt="{{cloze:Text}}<br>{{editable:Extra}}",
        css="",
        fields={"Text": "{{c1::to eat}}", "Extra": "verb"},
    )

    assert result["front_html"] == '<span class="cloze">[...]</span>'
    assert result["back_html"] == '<span class="cloze">to eat</span><br>verb'


def test_malformed_template_renders_best_effort_without_raising():
    result = render_card(
        qfmt="{{#Unclosed}}oops",
        afmt="{{Front}}",
        css="",
        fields={"Front": "hello"},
    )

    assert "oops" in result["front_html"]
    assert result["back_html"] == "hello"


def test_find_local_media_refs_finds_css_url_and_img_src():
    css = "@font-face { font-family: textbook; src: url('_HGSKyokashotai.ttf'); }"
    front_html = '<img src="_screenshot.png">'
    back_html = "<div>no media here</div>"

    refs = find_local_media_refs(css, front_html, back_html)

    assert refs == {"_HGSKyokashotai.ttf", "_screenshot.png"}


def test_find_local_media_refs_ignores_absolute_and_data_urls():
    css = "body { background: url('https://example.com/bg.png'); }"
    front_html = '<img src="data:image/png;base64,abc123">'
    back_html = ""

    refs = find_local_media_refs(css, front_html, back_html)

    assert refs == set()


def test_inline_local_media_replaces_only_the_matched_reference():
    css = "@font-face { src: url('_font.ttf'); }"
    front_html = '<img src="_pic.png"><p>_pic.png mentioned in text too</p>'
    back_html = ""
    media_data_uris = {
        "_font.ttf": "data:font/ttf;base64,Zm9udA==",
        "_pic.png": "data:image/png;base64,cGlj",
    }

    result = inline_local_media(css, front_html, back_html, media_data_uris)

    assert result["css"] == "@font-face { src: url('data:font/ttf;base64,Zm9udA=='); }"
    assert result["front_html"] == (
        '<img src="data:image/png;base64,cGlj"><p>_pic.png mentioned in text too</p>'
    )


def test_inline_local_media_leaves_unresolved_refs_untouched():
    css = "@font-face { src: url('_missing.ttf'); }"

    result = inline_local_media(css, "", "", {})

    assert result["css"] == css


def test_find_local_media_refs_finds_sound_tags():
    front_html = "彼は誘惑に負けた。[sound:anki-ai-cards-5.mp3]"
    back_html = "<div>no media here</div>"

    refs = find_local_media_refs("", front_html, back_html)

    assert refs == {"anki-ai-cards-5.mp3"}


def test_inline_local_media_replaces_sound_tag_with_inline_audio_element():
    front_html = "食べる[sound:anki-ai-cards-5.mp3]"
    data_uri = "data:audio/mpeg;base64,YWFh"
    media_data_uris = {"anki-ai-cards-5.mp3": data_uri}

    result = inline_local_media("", front_html, "", media_data_uris)

    assert result["front_html"] == f"食べる{_sound_play_button(data_uri)}"


def test_inline_local_media_leaves_unresolved_sound_tag_untouched():
    front_html = "食べる[sound:missing.mp3]"

    result = inline_local_media("", front_html, "", {})

    assert result["front_html"] == front_html
