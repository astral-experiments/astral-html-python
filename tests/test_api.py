from pathlib import Path

import pytest
from astral_html import parse


def test_parse_and_traverse() -> None:
    document = parse(
        '<main>Hello <a HREF="/guide?x=1&amp;y=2" href="ignored" disabled>'
        "Read <strong>the guide</strong></a>!</main>"
    )
    main, link, bold = document.elements()
    assert (main.tag, link.tag, bold.tag) == ("main", "a", "strong")
    assert main.text == "Hello Read the guide!"
    assert main.children == document.elements("A") == [link]
    assert main.elements() == [link, bold]
    assert link.children == [bold]
    assert link.parent == main

    attrs = link.attrs
    assert attrs == {"href": "/guide?x=1&y=2", "disabled": ""}
    attrs["href"] = "/changed"
    assert link.get("HREF") == "/guide?x=1&y=2"
    assert link.get("missing") is None
    fallback = object()
    assert link.get("missing", fallback) is fallback


def test_lexical_scopes_and_text_modes() -> None:
    document = parse("<P>one<p>two<script>if (a < b) x = '&amp;';</script>")
    outer, inner = document.elements("p")
    assert inner.parent == outer
    assert outer.text == "onetwoif (a < b) x = '&amp;';"
    assert document.select_one("html") is None


def test_newlines_are_normalized_in_text_and_attributes() -> None:
    (paragraph,) = parse('<p title="a\r\nb\rc">a\r\nb\rc</p>').elements()
    assert paragraph.text == paragraph.get("title") == "a\nb\nc"


def test_malformed_end_tags_void_elements_and_self_closing_scopes() -> None:
    source = (
        "<main><a>start <em>inner</main>tail</em>"
        '<section><input value="&amp;"><a><span/>x</a>outside</section>'
    )
    full = parse(source)
    main, first, _, section, field, second, span = full.elements()
    assert first.parent == main
    assert section.children == [field, second]
    assert section.text == "xoutside"
    assert field.get("value") == "&"
    assert span.text == "x"

    partial = parse(source, tags=["a"])
    assert [e.tag for e in partial.elements()] == ["a", "em", "a", "span"]
    for doc in (full, partial):
        assert [e.text for e in doc.elements("a")] == ["start inner", "x"]


@pytest.mark.parametrize("tags", [None, ["p"]])
def test_deep_mismatched_end_tags_close_innermost_scope(tags: list[str] | None) -> None:
    source = (
        "<div>" * 20
        + "<p>outer<p>first<i>child"
        + "</missing>" * 256
        + "</p>between<p>second<b>child</p><b>last</p>outside"
        + "<p>third<i>child</div>outside<p>fourth"
    )
    outer, first, second, third, fourth = parse(source, tags=tags).elements("p")
    assert (first.text, second.text) == ("firstchild", "secondchild")
    assert outer.text == "outerfirstchildbetweensecondchildlast"
    assert outer.elements("p") == [first, second]
    # </div> closes the third paragraph even when divs are discarded.
    assert (third.text, fourth.text) == ("thirdchild", "fourth")


@pytest.mark.parametrize("tags", [None, ["textarea", "style"]])
def test_rcdata_and_raw_text(tags: list[str] | None) -> None:
    doc = parse(
        "<textarea>&amp; <b>x</b></textarea><style>&amp; <b>x</b></style>", tags=tags
    )
    textarea, style = doc.elements()
    assert textarea.text == "& <b>x</b>"
    assert style.text == "&amp; <b>x</b>"


def test_partial_tree_roots_and_discarded_branches() -> None:
    source = "<main><h1>discard</h1><a>first <b>bold</b></a><aside><a>second</a>"
    doc = parse(source, tags=iter(["A"]))
    first, bold, second = doc.elements()
    assert (first.text, bold.text, second.text) == ("first bold", "bold", "second")
    assert first.parent is None
    assert doc.select("a > b") == [bold]
    assert doc.select("main a") == []
    assert doc.select(":root") == doc.select(":scope") == [first, second]


def test_partial_tree_with_nested_matches_or_empty_filter() -> None:
    source = '<div><a href="outer"><span><a href="inner">nested</a></span></a></div>'
    outer, span, inner = parse(source, tags=["a", "span"]).elements()
    assert (outer.get("href"), span.tag, inner.get("href")) == (
        "outer",
        "span",
        "inner",
    )
    assert parse(source, tags=[]).elements() == []


def test_sibling_selectors_across_discarded_ancestors() -> None:
    source = "<main><a>one</a>gap<b>b</b><a>two</a></main><section><a>three</a>"
    full = parse(source)
    _, two, _ = full.elements("a")
    assert (
        full.select("main > a + b + a") == full.select("main > a:nth-child(3)") == [two]
    )
    partial = parse(source, tags=["a"])
    _, two, three = partial.elements("a")
    assert partial.select("a + a") == [two, three]
    assert partial.select("a:nth-child(2)") == [two]


@pytest.mark.parametrize(
    ("page", "link_count"),
    [("iniconfig", 16), ("github-parse5", 99), ("wiki-42", 1604)],
)
def test_partial_parse_preserves_real_page_links(page: str, link_count: int) -> None:
    fixtures = Path(__file__).resolve().parents[1] / "benchmarks" / "fixtures"
    source = (fixtures / f"{page}.html").read_text(encoding="utf-8")

    def links(tags: list[str] | None) -> list[tuple[dict[str, str], str]]:
        return [(e.attrs, e.text) for e in parse(source, tags=tags).select("a")]

    full = links(None)
    assert len(full) == link_count
    assert links(["a"]) == full


def test_input_limits_include_discarded_content() -> None:
    source = "é" * (64 * 1024 * 1024 + 1)
    for tags in (None, ["a"]):
        parse("<div>" * 256 + "<br>", tags=tags)
        with pytest.raises(ValueError, match="nesting limit"):
            parse("<div>" * 257, tags=tags)
        with pytest.raises(ValueError, match="byte limit"):
            parse(source, tags=tags)


def test_empty_document_and_invalid_input() -> None:
    assert parse("").elements() == []
    with pytest.raises(TypeError):
        parse(b"<p>bytes</p>")  # ty: ignore[invalid-argument-type]
    with pytest.raises(TypeError):
        parse("", tags="a")
    with pytest.raises(TypeError):
        parse("", tags=[1])  # ty: ignore[invalid-argument-type]
    with pytest.raises(ValueError):
        parse("", tags=[""])
