from __future__ import annotations

import pytest
from astral_html import parse


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
    assert first.text == "firstchild"
    assert second.text == "secondchild"
    assert outer.text == "outerfirstchildbetweensecondchildlast"
    assert outer.elements("p") == [first, second]
    # The div end tag closes the third paragraph even when divs are discarded.
    assert third.text == "thirdchild"
    assert fourth.text == "fourth"
