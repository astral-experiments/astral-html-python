"""Resource regressions exercise the public API, including cancellation paths."""

import subprocess
import sys

import pytest
from astral_html import parse


def test_backtracking_limit_never_returns_partial_results() -> None:
    doc = parse("<main><b></b>" + "<i></i>" * 2_000 + "</main>")
    query = "b, :is(.missing ~ i) ~ i"
    first = doc.select_one("b")
    assert first is not None
    assert doc.select_one(query) == first
    with pytest.raises(ValueError, match="matching work limit"):
        doc.select(query)
    with pytest.raises(ValueError, match="matching work limit"):
        doc.select_one(":not(:is(.missing ~ i) ~ i) + .missing ~ i")
    assert len(doc.select("i")) == 2_000


def test_positional_selector_work_counts_even_without_sibling_traversal() -> None:
    doc = parse("<b><i></i></b>" * 2_048)
    query = ", ".join(["i:nth-child(even of *)"] * 256)
    with pytest.raises(ValueError, match="matching work limit"):
        doc.select(query)
    assert len(doc.select("i:first-child")) == 2_048


def test_wide_selector_work_counts_even_without_tree_traversal() -> None:
    doc = parse("<i></i>" * 4_000)
    query = ":is(" + ",".join([":not(*)"] * 2_048) + ")"
    with pytest.raises(ValueError, match="matching work limit"):
        doc.select(query)


def test_relative_cache_rotation_preserves_late_and_negated_matches() -> None:
    doc = parse("<i></i>" * 2_000 + "<i><b></b></i>")
    query = "i:has(.missing, b)"
    last = doc.select_one("i:last-child")
    assert last is not None
    assert doc.select(query) == [last]
    assert len(doc.select(f"i:not({query})")) == 2_000


def test_relative_cache_limit_within_a_single_candidate() -> None:
    doc = parse("<i></i>" * 8_192 + "<b></b>")
    # The rightmost tag matches only once. Clearing the cache only between
    # candidates, without a limit within that match, still retained 32 MiB.
    with pytest.raises(ValueError, match="relative-selector cache limit"):
        doc.select_one("i:has(.x, .y) ~ b")


@pytest.mark.skipif(sys.platform != "linux", reason="uses Linux peak RSS units")
def test_has_does_not_retain_a_bloom_filter_for_every_leaf() -> None:
    # Measure in a fresh interpreter, after parsing. The regression added
    # 65 MiB of peak RSS; the generous ceiling here is not a timing assertion.
    code = """
from resource import getrusage, RUSAGE_SELF
from astral_html import parse

doc = parse("<i></i>" * 16_000)
before = getrusage(RUSAGE_SELF).ru_maxrss
assert doc.select("i:has(.x, .y)") == []
print(getrusage(RUSAGE_SELF).ru_maxrss - before)
"""
    extra_kib = int(subprocess.check_output([sys.executable, "-c", code], timeout=20))
    assert extra_kib < 24 * 1024


def test_long_substrings_are_only_ascii_case_insensitive() -> None:
    needle = "a" * 64 + "Bé"
    doc = parse(f'<p data-value="x{needle}z"></p>')
    assert doc.select_one(f'[data-value*="{needle.lower()}" i]') is not None
    assert doc.select_one(f'[data-value*="{needle.upper()}" i]') is None


def test_selector_input_limit() -> None:
    with pytest.raises(ValueError, match="256 KiB input limit"):
        parse("").select("p" * (256 * 1024 + 1))
