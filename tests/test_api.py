import sys
from collections.abc import Mapping
from pathlib import Path

import pytest
from astral_html import ResourceLimitError, parse


def test_parse_and_traverse() -> None:
    document = parse(
        '<main>Hello <a HREF="/guide?x=1&amp;y=2" href="ignored" disabled>'
        "Read <strong>the guide</strong></a>!</main>"
    )
    main, link, bold = document.select("*")
    assert (main.tag, link.tag, bold.tag) == ("main", "a", "strong")
    assert main.text == "Hello Read the guide!"
    assert main.children == document.select("A") == [link]
    assert main.select("*") == [link, bold]
    assert link.children == [bold]
    assert link.parent == main

    attrs = link.attrs
    assert attrs == {"href": "/guide?x=1&y=2", "disabled": ""}
    with pytest.raises(TypeError):
        attrs["href"] = "/changed"  # ty: ignore[invalid-assignment]
    copied = dict(attrs)
    copied["href"] = "/changed"
    assert link["HREF"] == link.get("Href") == "/guide?x=1&y=2"
    assert link["disabled"] == ""
    assert "DISABLED" in link
    assert "missing" not in link
    with pytest.raises(KeyError) as missing:
        _ = link["ABSENT"]
    assert missing.value.args == ("ABSENT",)
    assert link.get("missing") is None
    fallback = object()
    assert link.get("missing", fallback) is fallback


def test_surrogate_attribute_name_is_missing() -> None:
    (link,) = parse('<a href="/">').select("a")
    key = b"\xff".decode(errors="surrogateescape")
    fallback = object()
    assert link.get(key, fallback) is link.attrs.get(key, fallback) is fallback
    assert key not in link
    with pytest.raises(TypeError):
        _ = 42 in link  # ty: ignore[unsupported-operator]
    with pytest.raises(KeyError) as missing:
        _ = link[key]
    assert missing.value.args == (key,)


def test_lexical_scopes_and_text_modes() -> None:
    document = parse("<P>one<p>two<script>if (a < b) x = '&amp;';</script>")
    outer, inner = document.select("p")
    assert inner.parent == outer
    assert outer.text == "onetwoif (a < b) x = '&amp;';"
    assert document.select_one("html") is None


def test_newlines_are_normalized_in_text_and_attributes() -> None:
    (paragraph,) = parse('<p title="a\r\nb\rc">a\r\nb\rc</p>').select("*")
    assert paragraph.text == paragraph.get("title") == "a\nb\nc"


@pytest.mark.parametrize("retain", [None, "p"])
def test_iter_text_preserves_fragment_boundaries(retain: str | None) -> None:
    doc = parse(
        "<main>outside<p>New<br>York</p><p>NewYork<br></p><p></p>"
        "<p> a\r\n<b>é &amp; </b><script>&amp;</script>end </p>after</main>",
        retain_subtrees=retain,
    )
    paragraphs = doc.select("p")
    expected = [["New", "York"], ["NewYork"], [], [" a\n", "é & ", "&amp;", "end "]]
    assert [list(p.iter_text()) for p in paragraphs] == expected
    assert [p.text for p in paragraphs] == ["".join(parts) for parts in expected]


def test_iter_text_iterator_lifetime_and_exhaustion() -> None:
    (p,) = parse("<p>a<i>b</i>c").select("p")
    first, second = p.iter_text(), p.iter_text()
    del p
    assert iter(first) is first
    assert next(first) == "a"
    assert list(second) == ["a", "b", "c"]
    assert list(first) == ["b", "c"]
    assert next(first, None) is None


@pytest.mark.parametrize("retain", [None, "p"])
def test_iter_content_preserves_direct_text_and_children(retain: str | None) -> None:
    (p,) = parse(
        "<div>outside<p><br>A<i>B<b>C</b></i>\r\n&amp;<br></p>outside",
        retain_subtrees=retain,
    ).select("p")
    first_break, italic, last_break = p.children
    content = p.iter_content()
    del p
    assert iter(content) is content
    assert list(content) == [first_break, "A", italic, "\n&", last_break]
    assert next(content, None) is None
    assert list(first_break.iter_content()) == []
    assert list(italic.iter_content()) == ["B", italic.children[0]]


def test_malformed_end_tags_void_elements_and_self_closing_scopes() -> None:
    source = (
        "<main><a>start <em>inner</main>tail</em>"
        '<section><input value="&amp;"><a><span/>x</a>outside</section>'
    )
    full = parse(source)
    main, first, _, section, field, second, span = full.select("*")
    assert first.parent == main
    assert section.children == [field, second]
    assert section.text == "xoutside"
    assert field.get("value") == "&"
    assert span.text == "x"

    partial = parse(source, retain_subtrees=["a"])
    assert [e.tag for e in partial.select("*")] == ["a", "em", "a", "span"]
    for doc in (full, partial):
        assert [e.text for e in doc.select("a")] == ["start inner", "x"]


@pytest.mark.parametrize("tags", [None, ["p"]])
def test_deep_mismatched_end_tags_close_innermost_scope(tags: list[str] | None) -> None:
    source = (
        "<div>" * 20
        + "<p>outer<p>first<i>child"
        + "</missing>" * 256
        + "</p>between<p>second<b>child</p><b>last</p>outside"
        + "<p>third<i>child</div>outside<p>fourth"
    )
    outer, first, second, third, fourth = parse(source, retain_subtrees=tags).select(
        "p"
    )
    assert (first.text, second.text) == ("firstchild", "secondchild")
    assert outer.text == "outerfirstchildbetweensecondchildlast"
    assert outer.select("p") == [first, second]
    # </div> closes the third paragraph even when divs are discarded.
    assert (third.text, fourth.text) == ("thirdchild", "fourth")


@pytest.mark.parametrize("tags", [None, ["textarea", "style"]])
def test_rcdata_and_raw_text(tags: list[str] | None) -> None:
    doc = parse(
        "<textarea>&amp; <b>x</b></textarea><style>&amp; <b>x</b></style>",
        retain_subtrees=tags,
    )
    textarea, style = doc.select("*")
    assert textarea.text == "& <b>x</b>"
    assert style.text == "&amp; <b>x</b>"


def test_partial_tree_roots_and_discarded_branches() -> None:
    source = "<main><h1>discard</h1><a>first <b>bold</b></a><aside><a>second</a>"
    doc = parse(source, retain_subtrees=iter(["A"]))
    first, bold, second = doc.select("*")
    assert (first.text, bold.text, second.text) == ("first bold", "bold", "second")
    assert first.parent is None
    assert doc.select("a > b") == [bold]
    assert doc.select("main a") == []
    assert doc.select(":root") == doc.select(":scope") == [first, second]


def test_retain_subtrees_accepts_a_single_tag_name() -> None:
    source = "<a>skip</a><article><b>keep</b></article>"
    (article,) = parse(source, retain_subtrees="ARTICLE").select(":root")
    assert (article.tag, article.text) == ("article", "keep")
    assert [child.tag for child in article.children] == ["b"]


def test_partial_tree_with_nested_matches_or_empty_filter() -> None:
    source = '<div><a href="outer"><span><a href="inner">nested</a></span></a></div>'
    outer, span, inner = parse(source, retain_subtrees=["a", "span"]).select("*")
    assert (outer.get("href"), span.tag, inner.get("href")) == (
        "outer",
        "span",
        "inner",
    )
    assert parse(source, retain_subtrees=[]).select("*") == []


def test_sibling_selectors_across_discarded_ancestors() -> None:
    source = "<main><a>one</a>gap<b>b</b><a>two</a></main><section><a>three</a>"
    full = parse(source)
    _, two, _ = full.select("a")
    assert (
        full.select("main > a + b + a") == full.select("main > a:nth-child(3)") == [two]
    )
    partial = parse(source, retain_subtrees=["a"])
    _, two, three = partial.select("a")
    assert partial.select("a + a") == [two, three]
    assert partial.select("a:nth-child(2)") == [two]


@pytest.mark.parametrize(
    ("page", "link_count"),
    [("iniconfig", 16), ("github-parse5", 99), ("wiki-42", 1604)],
)
def test_partial_parse_preserves_real_page_links(page: str, link_count: int) -> None:
    fixtures = Path(__file__).resolve().parents[1] / "benchmarks" / "fixtures"
    source = (fixtures / f"{page}.html").read_text(encoding="utf-8")

    def links(tags: list[str] | None) -> list[tuple[Mapping[str, str], str]]:
        return [
            (e.attrs, e.text) for e in parse(source, retain_subtrees=tags).select("a")
        ]

    full = links(None)
    assert len(full) == link_count
    assert links(["a"]) == full


def test_input_limits_include_discarded_content() -> None:
    source = "é" * (64 * 1024 * 1024 + 1)
    size_before = sys.getsizeof(source)
    for tags in (None, ["a"]):
        parse("<div>" * 256 + "<br>", retain_subtrees=tags)
        with pytest.raises(ResourceLimitError, match="nesting limit"):
            parse("<div>" * 257, retain_subtrees=tags)
        with pytest.raises(ResourceLimitError, match="byte limit"):
            parse(source, retain_subtrees=tags)
    assert sys.getsizeof(source) == size_before


def test_selector_byte_limit_on_python_strings() -> None:
    class MisleadingLength(str):
        def __len__(self) -> int:
            return 0

        def isascii(self) -> bool:
            return True

        def __getitem__(self, key: object, /) -> str:
            raise AssertionError("preflight must inspect the underlying string")

    doc = parse("<main><p/></main>")
    (main,) = doc.select("main")
    limit = 256 * 1024
    for query in (doc.select, doc.select_one, main.select, main.select_one):
        # ASCII and multibyte selectors at exactly the byte limit still parse.
        assert query(" " * (limit - 1) + "p")
        for char in ("é", "€", "🐍"):
            repeat, spaces = divmod(limit, len(char.encode()))
            boundary = char * repeat + " " * spaces
            assert not query(boundary)
            rejected = MisleadingLength(boundary + "a")
            size_before = sys.getsizeof(rejected)
            with pytest.raises(ResourceLimitError, match="256 KiB input limit"):
                query(rejected)
            assert sys.getsizeof(rejected) == size_before
        # A character count alone can also rule out the input immediately.
        oversized = "é" * (limit + 1)
        size_before = sys.getsizeof(oversized)
        with pytest.raises(ResourceLimitError, match="256 KiB input limit"):
            query(oversized)
        assert sys.getsizeof(oversized) == size_before


def test_unencodable_input_within_size_limit() -> None:
    with pytest.raises(UnicodeEncodeError):
        parse("x\udcff")
    # Exercise preflight for a string whose code point count alone is ambiguous.
    css = "x\udcff" + " " * (65 * 1024)
    with pytest.raises(UnicodeEncodeError) as caught:
        parse("").select(css)
    assert caught.value.object is css
    assert caught.value.start == 1


def test_text_outside_elements_does_not_consume_the_node_limit() -> None:
    # Each comment breaks the text into a separate token. Only descendants of
    # an element can be read back, so none of this prefix needs a tree node.
    doc = parse(
        "x<!---->" * 4_000_000 + "<p>one<i>!</p>between</missing><b>two</b>after"
    )
    first, second = doc.select(":root")
    assert (first.text, second.text) == ("one!", "two")
    assert doc.select("p + b:nth-child(2)") == [second]


def test_empty_document_and_invalid_input() -> None:
    assert parse("").select("*") == []
    with pytest.raises(TypeError):
        parse(b"<p>bytes</p>")  # ty: ignore[invalid-argument-type]
    with pytest.raises(ValueError):
        parse("", retain_subtrees="")
    with pytest.raises(TypeError):
        parse("", retain_subtrees=[1])  # ty: ignore[invalid-argument-type]
    with pytest.raises(ValueError):
        parse("", retain_subtrees=[""])
