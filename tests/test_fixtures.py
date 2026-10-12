from __future__ import annotations

from pathlib import Path

import pytest
from astral_html import Document, parse

FIXTURES = Path(__file__).resolve().parents[1] / "benchmarks" / "fixtures"


@pytest.mark.parametrize(
    ("name", "expected_links"),
    [("iniconfig.html", 16), ("github-parse5.html", 99), ("wiki-42.html", 1604)],
)
def test_real_pages_preserve_link_data_in_partial_parse(
    name: str, expected_links: int
) -> None:
    source = (FIXTURES / name).read_text(encoding="utf-8")
    full = parse(source)
    partial = parse(source, tags=["a"])

    def links(document: Document) -> list[tuple[dict[str, str], str]]:
        return [(element.attrs, element.text) for element in document.select("a")]

    full_links = links(full)
    assert len(full_links) == expected_links
    assert links(partial) == full_links
