import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from astral_html import ResourceLimitError, parse


def test_selector_limits_on_a_small_worker_stack() -> None:
    # A native stack overflow aborts Python. Run the boundary cases together
    # on a small worker stack, including the ones expected to succeed.
    subprocess.run(
        [sys.executable, "-X", "faulthandler", __file__], timeout=30, check=True
    )


def exercise_stack_limits() -> None:
    complexity = "matching complexity limit"

    def check(selector: str, expected: int | str, html: str = "<x></x>") -> None:
        select = parse(html).select
        if isinstance(expected, str):
            with pytest.raises(ResourceLimitError, match=expected):
                select(selector)
        else:
            assert len(select(selector)) == expected, selector

    check("i+" * 35_000 + "x", complexity, "<i></i>" * 35_000 + "<x></x>")
    check(":is(.missing ~ i) ~ i", "matching work limit", "<i></i>" * 2_000)
    chain = "i+" * 128 + "x"
    check("x, " + chain, complexity)
    check(f":is(x, {chain})", complexity)
    check(
        "i+" * 64 + ":is(" + "i+" * 64 + "x)", complexity, "<i></i>" * 128 + "<x></x>"
    )

    for depth in (32, 33, 10_000):
        check(":is(" * depth + "x" + ")" * depth, 1 if depth == 32 else "nesting limit")

    # Each selector consumes the whole matching-depth budget, then exceeds it
    # by one sibling. Nested functions use part of that same budget.
    for prefix, allowed, matches in [
        ("", 128, 1),
        (":is(", 127, 1),
        (":where(", 127, 1),
        ("x:not(", 127, 0),
        (":nth-child(1 of ", 127, 1),
        (":nth-last-child(1 of ", 127, 1),
        ("main:has(", 126, 1),
        (":is(" * 32, 96, 1),
        (":nth-child(1 of " * 32, 96, 1),
    ]:
        for count, expected in ((allowed, matches), (allowed + 1, complexity)):
            chain = "i+" * (count - 1) + "x"
            selector = prefix + chain + ")" * prefix.count("(")
            html = "<main>" + "<i></i>" * (count - 1) + "<x></x></main>"
            check(selector, expected, html)

    # :has() recurses through the tree as well as through the selector.
    for wrappers in (0, 31):
        depth = 125 - wrappers
        doc = parse("<main>" + "<div>" * 254 + "<i></i>" * depth + "<x></x>")
        for step in ("i+", "div>"):
            selector = (
                ":is(" * wrappers
                + "main:has("
                + step * depth
                + "x"
                + ")" * (wrappers + 1)
            )
            (main,) = doc.select(selector)
            assert main.tag == "main"
            assert doc.select_one(selector) == main


def test_wide_lists_and_long_compounds_fit_the_depth_budget() -> None:
    value = "(" * 256
    doc = parse(f'<p class="x" data-value="{value}"></p>')
    wide = ",".join(["p"] * 512)
    for selector in (wide, f":is({wide})", ".x" * 512, f'[data-value="{value}"]'):
        assert len(doc.select(selector)) == 1


def test_work_limit_discards_matches_and_allows_subsequent_queries() -> None:
    doc = parse("<b></b>" + "<i></i>" * 2_000)
    query = "b, :is(.missing ~ i) ~ i"
    assert doc.select_one(query) == doc.select("b")[0]
    with pytest.raises(ResourceLimitError, match="matching work limit"):
        doc.select(query)
    with pytest.raises(ResourceLimitError, match="matching work limit"):
        doc.select_one(":not(:is(.missing ~ i) ~ i) + .missing ~ i")
    assert len(doc.select("i")) == 2_000


def test_work_limit_without_tree_traversal() -> None:
    doc = parse("<b><i></i></b>" * 2_048)
    with pytest.raises(ResourceLimitError, match="matching work limit"):
        doc.select(", ".join(["i:nth-child(even of *)"] * 256))
    assert len(doc.select("i:first-child")) == 2_048

    wide = ",".join([":not(*)"] * 2_048)
    with pytest.raises(ResourceLimitError, match="matching work limit"):
        parse("<i></i>" * 4_000).select(f":is({wide})")


def test_selector_alternatives_are_charged_individually() -> None:
    doc = parse("<i></i>" * 5_000)
    tags = ", ".join(f"x{i}" for i in range(33))
    assert doc.select(tags) == []
    assert doc.select(f"{tags}, i") == doc.select("i")
    unused = ", ".join(f"x{i}" for i in range(1024))
    assert doc.select(f"i, {unused}") == doc.select("i")


def test_unrelated_has_does_not_charge_nth_child_to_relative_cache() -> None:
    doc = parse("<i></i>" * 9_000 + "<b></b>")
    b = doc.select_one("b:nth-child(9001)")
    assert b is not None
    assert doc.select_one("b:nth-child(9001), x:has(*)") == b


def test_repeated_tag_name_scans_on_a_shared_ancestor_are_bounded() -> None:
    tag = "x" * 8192
    doc = parse(f"<{tag}>" + "<i></i>" * 2000)
    with pytest.raises(ResourceLimitError, match="matching work limit"):
        doc.select(tag[:-1] + "y > i")
    # A mismatch in the first byte or in the length is cheap.
    assert doc.select("y" + tag[1:] + " > i") == []
    assert doc.select("x > i") == []


@pytest.mark.parametrize("open_block, close_block", [("[", "]"), ("{", "}")])
def test_selector_nesting_limit_without_parentheses(
    open_block: str, close_block: str
) -> None:
    selector = open_block * 33 + "x" + close_block * 33
    for suffix in ("", "/*(*/"):
        with pytest.raises(ResourceLimitError, match="nesting limit"):
            parse("").select(selector + suffix)


@pytest.mark.parametrize("pseudo", ["is", "where"])
@pytest.mark.parametrize(
    "missing", ["tag", "#id", ".class", "[name]", "[name=value]", "[*|name]"]
)
def test_nested_lists_charge_leaf_checks_as_they_run(pseudo: str, missing: str) -> None:
    doc = parse("<i></i>" * 4096)
    alternatives = ",".join([missing] * 1024)
    assert doc.select(f":{pseudo}(i,{alternatives})") == doc.select("i")
    with pytest.raises(ResourceLimitError, match="matching work limit"):
        doc.select(f":{pseudo}({alternatives})")


def test_nth_of_type_bounds_sibling_name_scans() -> None:
    name = "a" * 16_384
    # Sibling names share a long prefix. :nth-of-type compares the candidates
    # with earlier siblings even when the selector has no literal tag name.
    siblings = [f"{name}{n:03}" for n in range(80)]
    doc = parse("".join(f"<{tag}></{tag}>" for tag in siblings))
    with pytest.raises(ResourceLimitError, match="matching work limit"):
        doc.select(":nth-of-type(2)")


def test_repeated_attribute_value_scans_are_bounded() -> None:
    value = "first " + "word " * 200_000 + "last"
    doc = parse(f'<p class="{value}">')
    for missing in (".absent", "[class~=absent]", "[class*=absent i]"):
        with pytest.raises(ResourceLimitError, match="matching work limit"):
            doc.select(",".join([missing] * 128))

    # One complete scan is fine, as are repeated operations that only inspect
    # the beginning, end, or length of this attribute.
    large = parse(f'<p class="{"x" * (9 * 1024 * 1024)} last">')
    assert len(large.select(".last")) == 1
    cheap = (
        ".first[class][class^=first][class$=last][class*=FIRST i]:not([class=short])"
    )
    assert len(doc.select(cheap * 64)) == 1


def test_repeated_attribute_name_scans_are_bounded() -> None:
    attrs = " ".join(f"a{i}" for i in range(50_000))
    doc = parse(f"<p {attrs} last>")
    assert len(doc.select("[last]")) == 1
    with pytest.raises(ResourceLimitError, match="matching work limit"):
        doc.select(",".join(["[absent]"] * 256))


def test_attribute_matches_on_shared_ancestor_can_short_circuit() -> None:
    value = "xxFIRST" + "a" * 8192
    doc = parse(f'<section data-key="{value}" id="{value}" {value}>' + "<a></a>" * 4000)
    links = doc.select("a")
    other = "z" + value[1:]
    for selector in (
        "[data-key*=FIRST]",
        "[data-key*=first i]",
        f'[data-key*="first{"a" * 32}" i]',
    ):
        assert doc.select(f"section{selector} a") == links
    for selector in [f"[{other}]", f"#{other}"] + [
        f'[data-key{op}"{other}"]' for op in ("=", "^=", "$=", "|=")
    ]:
        assert doc.select(f"section{selector} a") == []

    # One name check plus an early comparison should cost about the same as
    # either alone, even when many descendants consult the same ancestor.
    many = parse(f"<section {value}>" + "<a></a>" * 160_000)
    assert many.select(f"section[{other}] a") == []


def test_substring_crossing_scan_blocks() -> None:
    needle = "é" + "B" * 40
    # A multibyte character straddles the scan boundary. The long insensitive
    # search must see the entire needle, even when it spans two blocks.
    doc = parse(f'<p data-value="{"a" * 63}{needle}suffix">')
    assert len(doc.select(f'[data-value*="{needle}"]')) == 1
    assert len(doc.select(f'[data-value*="{needle.lower()}" i]')) == 1
    assert doc.select(f'[data-value*="{needle.upper()}" i]') == []
    assert len(doc.select('[data-value*="suffix"]')) == 1


def test_relative_cache_rotation_preserves_late_and_negated_matches() -> None:
    doc = parse("<i></i>" * 2_000 + "<i><b></b></i>")
    query = "i:has(.missing, b)"
    assert doc.select(query) == [doc.select_one("i:last-child")]
    assert len(doc.select(f"i:not({query})")) == 2_000


def test_relative_cache_limit_within_one_candidate() -> None:
    doc = parse("<i></i>" * 8_192 + "<b></b>")
    with pytest.raises(ResourceLimitError, match="relative-selector cache limit"):
        doc.select_one("i:has(.x, .y) ~ b")


def test_nth_index_cache_rotation_preserves_matches() -> None:
    doc = parse(("<p>" + "<i></i>" * 8 + "</p>") * 2048)
    selector = ", ".join(["i:nth-child(0 of *)"] * 6 + ["i:nth-child(8 of *)"])
    assert doc.select(selector) == doc.select("i:last-child")


@pytest.mark.skipif(sys.platform != "linux", reason="uses Linux peak RSS units")
@pytest.mark.parametrize(
    ("fragment", "count", "selector", "max_mib"),
    [
        # Unbounded relative Bloom filters used 65 MiB; unbounded nth indexes
        # used 57 MiB. Short sibling groups avoid quadratic debug assertions.
        ("<i></i>", 16_000, "i:has(.x, .y)", 24),
        (
            "<p>" + "<i></i>" * 4 + "</p>",
            65_000,
            ",".join(["i:nth-child(0 of *)"] * 6),
            48,
        ),
    ],
)
def test_selector_cache_memory(
    fragment: str, count: int, selector: str, max_mib: int
) -> None:
    code = """
import sys
from resource import getrusage, RUSAGE_SELF
from astral_html import parse
doc = parse(sys.argv[1] * int(sys.argv[2]))
before = getrusage(RUSAGE_SELF).ru_maxrss
assert doc.select(sys.argv[3]) == []
print(getrusage(RUSAGE_SELF).ru_maxrss - before)
"""
    args = [sys.executable, "-c", code, fragment, str(count), selector]
    extra_kib = int(subprocess.check_output(args, timeout=30))
    assert extra_kib < max_mib * 1024


def test_selector_input_limit() -> None:
    with pytest.raises(ResourceLimitError, match="256 KiB input limit"):
        parse("").select("p" * (256 * 1024 + 1))


if __name__ == "__main__":
    # If a platform disallows both small sizes, still test its default stack.
    for stack_size in (65536, 131072):
        try:
            threading.stack_size(stack_size)
        except RuntimeError, ValueError:
            continue
        break
    with ThreadPoolExecutor(max_workers=1) as worker:
        worker.submit(exercise_stack_limits).result()
