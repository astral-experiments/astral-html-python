"""Behavior specific to the Servo-backed Python parser prototype."""

import pytest
from astral_html import parse


def test_implied_elements_and_paragraph_recovery() -> None:
    document = parse("<p>first<p>second")
    html, head, body, first, second = document.elements()
    assert (html.tag, head.tag, body.tag) == ("html", "head", "body")
    assert body.children == [first, second]
    assert [element.text for element in document.select("body > p")] == [
        "first",
        "second",
    ]


def test_table_foster_parenting_and_implied_table_body() -> None:
    document = parse("<table>outside<tr><td>inside</table>")
    body = document.elements("body")[0]
    table = document.elements("table")[0]
    assert body.text == "outsideinside"
    assert table.text == "inside"
    assert [element.tag for element in table.select(":scope > tbody > tr > td")] == [
        "td"
    ]


def test_misnested_formatting_is_reconstructed() -> None:
    document = parse("<b><i>one</b>two</i>")
    bold = document.elements("b")[0]
    first, second = document.elements("i")
    assert bold.text == "one"
    assert first.parent == bold
    assert second.parent == document.elements("body")[0]
    assert second.text == "two"


def test_partial_tree_keeps_recovered_link_subtrees() -> None:
    document = parse(
        '<table><tr><td><a href="/first">one</a></table><a>two', tags=["a"]
    )
    first, second = document.elements()
    assert (first.get("href"), first.text) == ("/first", "one")
    assert (second.get("href"), second.text) == (None, "two")
    assert [element.tag for element in document.select(":root")] == ["a", "a"]


def test_noscript_fallback_markup_is_queryable_without_scripting() -> None:
    document = parse('<body><noscript><a href="/fallback">fallback</a></noscript>')
    (link,) = document.select("noscript a[href]")
    assert (link.get("href"), link.text) == ("/fallback", "fallback")


def test_legacy_parser_remains_available_for_direct_comparisons() -> None:
    document = parse("<p>first<p>second", parser="lexical")
    first, second = document.elements()
    assert first.children == [second]
    assert first.text == "firstsecond"
    with pytest.raises(ValueError, match="parser must be"):
        parse("<p>", parser="unknown")  # ty: ignore[invalid-argument-type]
