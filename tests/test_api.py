from __future__ import annotations

import pytest
from astral_html import parse


def test_parse_and_traverse() -> None:
    document = parse(
        '<main id="content">Hello <a HREF="/guide?x=1&amp;y=2" '
        'href="ignored" disabled>Read <strong>the guide</strong></a>!</main>'
    )

    assert [element.tag for element in document.elements()] == ["main", "a", "strong"]
    assert [element.tag for element in document.elements("A")] == ["a"]
    main = document.select_one("main")
    assert main is not None
    assert main.text == "Hello Read the guide!"
    assert [child.tag for child in main.children] == ["a"]
    assert [element.tag for element in main.elements()] == ["a", "strong"]

    link = main.select_one("a")
    assert link is not None
    attrs = link.attrs
    assert attrs == {"href": "/guide?x=1&y=2", "disabled": ""}
    attrs["href"] = "/changed"
    assert link.get("HREF") == "/guide?x=1&y=2"
    assert link.get("missing") is None
    fallback = object()
    assert link.get("missing", fallback) is fallback
    assert link.parent is not None
    assert link.parent.tag == "main"
    assert [child.tag for child in link.children] == ["strong"]


def test_document_uses_lexical_scopes_and_text_modes() -> None:
    # Unlike a browser, astral-html does not imply html/body or close the
    # previous paragraph when another p start tag appears.
    document = parse("<P>one<p>two<script>if (a < b) x = '&amp;';</script>")
    paragraphs = document.elements("p")
    assert len(paragraphs) == 2
    assert paragraphs[1].parent is not None
    assert paragraphs[1].parent.tag == "p"
    assert paragraphs[0].text == "onetwoif (a < b) x = '&amp;';"
    assert document.select_one("html") is None


def test_newlines_are_normalized_in_text_and_attributes() -> None:
    document = parse('<p title="a\r\nb\rc">a\r\nb\rc</p>')
    paragraph = document.select_one("p")
    assert paragraph is not None
    assert paragraph.text == "a\nb\nc"
    assert paragraph.get("title") == "a\nb\nc"


def test_malformed_end_tags_void_elements_and_self_closing_scopes() -> None:
    source = (
        '<main><a href="/a">start <em>inner</main>tail</em>'
        '<section><input value="&amp;"><a href="/b"><span/>x</a>outside</section>'
    )
    document = parse(source)
    links = document.select("a")
    assert [link.text for link in links] == ["start inner", "x"]
    assert links[0].parent is not None
    assert links[0].parent.tag == "main"
    section = document.select_one("section")
    assert section is not None
    assert [child.tag for child in section.children] == ["input", "a"]
    assert section.text == "xoutside"
    input_element = section.select_one("input")
    span = links[1].select_one("span")
    assert input_element is not None
    assert span is not None
    assert input_element.get("value") == "&"
    assert span.text == "x"

    partial = parse(source, tags=["a"])
    assert [link.text for link in partial.select("a")] == ["start inner", "x"]
    assert [element.tag for element in partial.elements()] == ["a", "em", "a", "span"]


def test_rcdata_and_raw_text_are_preserved_in_partial_parse() -> None:
    source = (
        "<div><textarea>&amp; <b>text</b></textarea>"
        "<style>&amp; <b>literal</b></style></div>"
    )
    for document in (parse(source), parse(source, tags=["textarea", "style"])):
        textarea = document.select_one("textarea")
        style = document.select_one("style")
        assert textarea is not None
        assert style is not None
        assert textarea.text == "& <b>text</b>"
        assert style.text == "&amp; <b>literal</b>"
        assert document.select("b") == []


@pytest.mark.parametrize("tags", [None, ["a"]])
def test_nesting_limit_applies_even_when_tags_are_discarded(
    tags: list[str] | None,
) -> None:
    # 256 open non-void elements are allowed; void elements do not add depth.
    document = parse("<div>" * 256 + "<br>", tags=tags)
    assert document is not None
    with pytest.raises(ValueError, match="nesting limit"):
        parse("<div>" * 257, tags=tags)


def test_selectors_match_and_return_source_order_without_duplicates() -> None:
    document = parse(
        '<main id="catalog">'
        '<article class="card featured" data-kind="book">'
        '<h2>First</h2><a class="buy external" href="/first">Buy</a>'
        '<span class="price">10</span><span class="price sale">8</span>'
        "</article>"
        '<article class="card" data-kind="game">'
        '<h2>Second</h2><a class="buy" href="/second">Buy</a>'
        "</article></main>"
    )

    def texts(selector: str) -> list[str]:
        return [element.text for element in document.select(selector)]

    assert texts("#catalog article.card h2") == ["First", "Second"]
    assert texts('article[data-kind="book"] > a.buy[href]') == ["Buy"]
    assert texts("article.featured > a + span") == ["10"]
    assert texts("article.featured > a ~ span") == ["10", "8"]
    assert texts(".sale, .price") == ["10", "8"]
    assert [element.tag for element in document.select("main > *")] == [
        "article",
        "article",
    ]
    assert document.select(".does-not-exist") == []
    assert document.select_one(".does-not-exist") is None


def test_element_queries_only_search_descendants() -> None:
    document = parse(
        '<main><section id="one"><a href="/one">one</a></section>'
        '<section id="two"><a href="/two">two</a></section></main>'
    )
    section = document.select_one("#one")
    assert section is not None
    assert section.select("section") == []
    assert [element.get("href") for element in section.select("a")] == ["/one"]
    assert [element.get("href") for element in section.select("main a")] == ["/one"]
    assert section.select_one("#two a") is None
    assert section.elements("section") == []


def test_structural_and_scoped_css_selectors() -> None:
    document = parse(
        '<main id="some:id"><ul><li class="item">One</li>'
        '<li class="item featured"><a href="/two">Two</a></li>'
        '<li class="item">Three</li></ul></main>'
    )
    main = document.select_one(r"#some\:id")
    assert main is not None
    root = document.select_one(":root")
    assert root is not None
    assert root.tag == "main"
    assert [element.text for element in document.select("li:first-child")] == ["One"]
    assert [element.text for element in document.select("li:nth-child(2)")] == ["Two"]
    assert [element.text for element in document.select("li:not(.featured)")] == [
        "One",
        "Three",
    ]
    assert [element.text for element in document.select("li:has(> a[href])")] == ["Two"]
    assert [element.tag for element in main.select(":scope > ul")] == ["ul"]


def test_tagged_selectors_and_nested_alternatives() -> None:
    document = parse(
        '<main><a href="/one">one</a><span><a href="/two">two</a></span></main>'
    )

    assert [element.text for element in document.select("main A[href]")] == [
        "one",
        "two",
    ]
    assert [element.text for element in document.select(r"\61 [href]")] == [
        "one",
        "two",
    ]
    assert [element.tag for element in document.select(":is(span, a)")] == [
        "a",
        "span",
        "a",
    ]
    assert [element.tag for element in document.select("span, a")] == ["a", "span", "a"]
    assert [element.tag for element in document.select("span:has(a)")] == ["span"]


@pytest.mark.parametrize("selector", ["", "[", "div >", "div,,span", "."])
def test_invalid_selectors_raise_value_error(selector: str) -> None:
    with pytest.raises(ValueError):
        parse("<div></div>").select(selector)


def test_unsupported_dynamic_pseudo_class_is_rejected() -> None:
    with pytest.raises(ValueError, match="a:hover"):
        parse("<a>link</a>").select("a:hover")


def test_partial_parse_keeps_selected_subtrees_and_discards_other_branches() -> None:
    source = (
        '<main><h1>Discard</h1><a href="/a">First <b>bold</b></a>'
        '<aside><a href="/b">Second <i>italic</i></a></aside>'
        "<p>Discard too</p></main>"
    )
    document = parse(source, tags=(tag for tag in ["A"]))

    assert [element.tag for element in document.elements()] == ["a", "b", "a", "i"]
    assert [element.text for element in document.select("a")] == [
        "First bold",
        "Second italic",
    ]
    assert [element.text for element in document.select("a > b")] == ["bold"]
    assert document.select("main a") == []
    assert document.select("h1, aside, p") == []
    for selector in (":root", ":scope"):
        assert [element.get("href") for element in document.select(selector)] == [
            "/a",
            "/b",
        ]
    first = document.select_one("a")
    assert first is not None
    assert first.parent is None


def test_partial_parse_handles_nested_matches_and_empty_filter() -> None:
    source = '<div><a href="outer"><span><a href="inner">nested</a></span></a></div>'
    document = parse(source, tags=["a", "span"])
    assert [element.tag for element in document.elements()] == ["a", "span", "a"]
    assert [element.get("href") for element in document.select("a")] == [
        "outer",
        "inner",
    ]
    assert parse(source, tags=[]).elements() == []


def test_sibling_selectors_across_retained_and_discarded_ancestors() -> None:
    source = (
        '<main><a id="one">A<i>X</i></a>gap<b>B</b><a id="two">C</a></main>'
        '<section><a id="three">D</a></section>'
    )
    full = parse(source)
    assert [element.get("id") for element in full.select("main > a + b + a")] == ["two"]
    assert [element.get("id") for element in full.select("main > a:nth-child(3)")] == [
        "two"
    ]

    partial = parse(source, tags=["a"])
    assert [element.get("id") for element in partial.select("a + a")] == [
        "two",
        "three",
    ]
    assert [element.get("id") for element in partial.select("a:nth-child(2)")] == [
        "two"
    ]


def test_input_byte_limit_applies_to_full_and_partial_parses() -> None:
    source = "é" * (64 * 1024 * 1024 + 1)
    for tags in (None, ["a"]):
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
