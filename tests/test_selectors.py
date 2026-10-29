import pytest
from astral_html import parse


def test_matching_and_source_order() -> None:
    doc = parse(
        '<main id="some:id"><ul>'
        '<li class="item featured" data-kind="book">one</li>'
        '<li class="item"><a href="/two">two</a></li>'
        '<li class="item">three</li></ul></main>'
    )
    one, two, three = doc.select("li")
    (main,) = doc.select("main")
    assert doc.select_one(r"#some\:id") == doc.select_one(":root") == main
    assert main.select(":scope > ul") == main.select(":scope > *") == doc.select("ul")
    assert doc.select("main .item") == [one, two, three]
    assert doc.select('[data-kind="book"] + li') == [two]
    assert doc.select(".featured ~ li") == [two, three]
    assert doc.select("li:last-child, li, .featured") == [one, two, three]
    assert doc.select("li:first-child") == [one]
    assert doc.select("li:nth-child(2)") == [two]
    assert doc.select("li:not(.featured)") == [two, three]
    assert doc.select("li:has(> a[href])") == [two]
    assert doc.select(".missing") == []
    assert doc.select_one(".missing") is None


def test_queries_from_an_element_only_return_descendants() -> None:
    doc = parse('<main><section><a>one</a></section><section id="two"><a>two</a>')
    section = doc.select("section")[0]
    assert section.select("section") == []
    assert section.select("main a") == section.select("a") == [doc.select("a")[0]]
    assert section.select_one("#two a") is None


def test_tagged_selectors_and_nested_alternatives() -> None:
    doc = parse('<main><a href="/">one</a><span><a href="/">two</a></span></main>')
    _, one, span, two = doc.select("*")
    assert doc.select("main A[href]") == doc.select(r"\61 [href]") == [one, two]
    assert doc.select("|a[href]") == [one, two]
    assert doc.select(":is(span, a)") == doc.select("span, a") == [one, span, two]
    assert doc.select("span:has(a)") == [span]


def test_class_tokens_use_html_whitespace() -> None:
    doc = parse("".join(f'<p class="foo{space}bar"></p>' for space in " \t\n\r\f\v"))
    *spaces, vertical_tab = doc.select("*")
    assert doc.select(".foo") == spaces
    assert doc.select(r".foo\b bar") == [vertical_tab]


def test_long_substrings_are_only_ascii_case_insensitive() -> None:
    needle = "a" * 64 + "Bé"
    doc = parse(f'<p data-value="x{needle}z"></p>')
    assert doc.select_one(f'[data-value*="{needle.lower()}" i]') is not None
    assert doc.select_one(f'[data-value*="{needle.upper()}" i]') is None


@pytest.mark.parametrize("selector", ["", "[", "div >", "div,,span", ".", "a:hover"])
def test_invalid_and_unsupported_selectors(selector: str) -> None:
    with pytest.raises(ValueError, match="invalid CSS selector") as error:
        parse("<a>").select(selector)
    assert selector in str(error.value)


@pytest.mark.parametrize(
    "selector",
    [
        ":host",
        ":host(div)",
        ":HOST(div)",
        r":h\6fst(div)",
        "p, :host(div)",
        ":not(:host(div))",
        "div:has(:host(div))",
        ":nth-child(1 of :host(div))",
    ],
)
def test_shadow_host_is_unsupported(selector: str) -> None:
    with pytest.raises(ValueError, match="invalid CSS selector"):
        parse("<div><p>").select(selector)


@pytest.mark.parametrize(
    ("selector", "tags"),
    [
        (":is(:host(div), p)", ["p"]),
        (":where(:host(div), p)", ["p"]),
        (r":is(:h\6fst(div), p)", ["p"]),
        (":is(:not(:host(div)), p)", ["p"]),
        (":not(:is(:host(div), p))", ["div"]),
        (":is(:host(div))", []),
        ("div:has(:is(:host(div), p))", ["div"]),
    ],
)
def test_shadow_host_in_forgiving_selector_lists(
    selector: str, tags: list[str]
) -> None:
    assert [e.tag for e in parse("<div><p>").select(selector)] == tags


def test_host_text_in_strings_comments_and_identifiers_is_preserved() -> None:
    doc = parse('<p data-value=":host(div)" class="host(foo)"></p>')
    for selector in ['[data-value=":host(div)"]', "p/*:host(div)*/", r".host\(foo\)"]:
        assert len(doc.select(selector)) == 1
