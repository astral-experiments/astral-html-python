from astral_html import parse


def test_class_tokens_use_html_whitespace() -> None:
    document = parse(
        '<p id="space" class="foo bar">'
        '<p id="tab" class="foo\tbar">'
        '<p id="lf" class="foo\nbar">'
        '<p id="cr" class="foo\rbar">'
        '<p id="ff" class="foo\fbar">'
        '<p id="vt" class="foo\vbar">'
    )

    assert [element.get("id") for element in document.select(".foo")] == [
        "space",
        "tab",
        "lf",
        "cr",
        "ff",
    ]
    assert [element.get("id") for element in document.select(r".foo\b bar")] == ["vt"]
