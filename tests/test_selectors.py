import pytest
from astral_html import InvalidSelectorError, ResourceLimitError, parse


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


@pytest.mark.parametrize("selector", ["div >", "a:hover"])
def test_invalid_and_unsupported_selectors(selector: str) -> None:
    with pytest.raises(InvalidSelectorError, match="invalid CSS selector") as error:
        parse("<a>").select(selector)
    assert selector in str(error.value)


@pytest.mark.parametrize(
    ("selector", "error_type"),
    [("a:hover", InvalidSelectorError), ("a" * (256 * 1024 + 1), ResourceLimitError)],
    ids=["unsupported", "input-limit"],
)
def test_query_errors_are_distinct_value_errors(
    selector: str, error_type: type[ValueError]
) -> None:
    doc = parse("<main><a></a></main>")
    (main,) = doc.select("main")
    for scope in (doc, main):
        for query in (scope.select, scope.select_one):
            with pytest.raises(ValueError) as error:
                query(selector)
            assert type(error.value) is error_type


@pytest.mark.parametrize(
    "selector",
    [
        ":host",
        r"p, :H\6fst(div)",
        ":not(:host(div))",
    ],
)
def test_shadow_host_is_unsupported(selector: str) -> None:
    with pytest.raises(InvalidSelectorError, match="invalid CSS selector"):
        parse("<div><p>").select(selector)


@pytest.mark.parametrize(
    ("selector", "tags"),
    [
        (":is(:host(div), p)", ["p"]),
        (":where(:not(:host(div)), p)", ["p"]),
        (":is(:host(div))", []),
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


def test_relative_selectors_search_sibling_subtrees_from_the_anchor() -> None:
    doc = parse(
        "<p id='one'></p><p id='two'><b><i></i></b></p><p id='three'></p><i></i>"
    )
    one, two, three = doc.select("p")
    assert doc.select("p:has(+ p > b i)") == [one]
    assert doc.select("p:has(~ p b > i)") == [one]
    assert doc.select("p:has(+ p + i)") == [two]
    assert doc.select("p:has(+ i)") == [three]


def test_reverse_sibling_ranks_skip_nonmatching_siblings() -> None:
    doc = parse("<b class='q'></b><i></i><b></b><i class='q'></i><b class='q'></b>")
    one, _, three, four, five = doc.select("*")
    assert doc.select(":nth-last-child(2 of .q)") == [four]
    assert doc.select("b:nth-last-of-type(2)") == [three]
    assert doc.select(":nth-last-child(odd of .q)") == [one, five]
