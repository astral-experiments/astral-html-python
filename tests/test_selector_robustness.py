import json
import subprocess
import sys

import pytest
from astral_html import parse


def query_in_subprocess(
    css: str,
    html: str,
    expected: int | str,
    method: str = "select",
    *,
    worker: bool = False,
) -> None:
    # A native stack overflow aborts Python, so both rejection and boundary
    # matching must run outside the pytest process.
    code = """
import json
import sys
import threading
from astral_html import parse
css, html, method, worker = json.load(sys.stdin)
document = parse(html)
def query():
    try:
        result = getattr(document, method)(css)
    except ValueError as error:
        print(error)
    else:
        print(len(result) if method == 'select' else int(result is not None))
if worker:
    # The minimum varies by platform; both sizes exercise a small stack.
    for stack_size in (65536, 131072):
        try:
            threading.stack_size(stack_size)
        except (RuntimeError, ValueError):
            continue
        break
    else:
        sys.exit(77)
    thread = threading.Thread(target=query)
    thread.start()
    thread.join()
else:
    query()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps([css, html, method, worker]),
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    if result.returncode == 77:
        pytest.skip("thread stack size is unsupported on this platform")
    assert result.returncode == 0, result.stderr
    if isinstance(expected, int):
        assert result.stdout.strip() == str(expected)
    else:
        assert expected in result.stdout


def test_long_sibling_chain_is_rejected_without_aborting() -> None:
    query_in_subprocess(
        "i+" * 35_000 + "x",
        "<main>" + "<i></i>" * 35_000 + "<x></x></main>",
        "matching complexity limit",
    )


def test_matching_work_limit_unwinds_on_a_small_worker_stack() -> None:
    query_in_subprocess(
        ":is(.missing ~ i) ~ i", "<i></i>" * 2_000, "matching work limit", worker=True
    )


@pytest.mark.parametrize(
    ("template", "compounds", "matches"),
    [
        ("{}", 128, 1),
        (":is({})", 127, 1),
        (":where({})", 127, 1),
        ("x:not({})", 127, 0),
        (":nth-child(1 of {})", 127, 1),
        (":nth-last-child(1 of {})", 127, 1),
        ("main:has({})", 126, 1),
    ],
)
def test_matching_depth_boundary_includes_nested_functions(
    template: str, compounds: int, matches: int
) -> None:
    for count in [compounds, compounds + 1]:
        chain = "i+" * (count - 1) + "x"
        query_in_subprocess(
            template.format(chain),
            "<main>" + "<i></i>" * (count - 1) + "<x></x></main>",
            matches if count == compounds else "matching complexity limit",
        )


@pytest.mark.parametrize("template", ["x, {}", ":is(x, {})"])
def test_overlong_chain_is_checked_before_matching_or_short_circuiting(
    template: str,
) -> None:
    query_in_subprocess(
        template.format("i+" * 128 + "x"), "<x></x>", "matching complexity limit"
    )


def test_nested_chains_share_the_matching_depth_budget() -> None:
    # Each individual chain fits, but evaluating the inner one while matching
    # the outer one would exceed the shared stack-depth budget.
    query_in_subprocess(
        "i+" * 64 + ":is(" + "i+" * 64 + "x)",
        "<i></i>" * 128 + "<x></x>",
        "matching complexity limit",
    )


def test_selector_nesting_limit_and_safe_boundary() -> None:
    for count in [32, 33, 10_000]:
        query_in_subprocess(
            ":is(" * count + "x" + ")" * count,
            "<x></x>",
            1 if count == 32 else "nesting limit",
        )


@pytest.mark.parametrize("function", ["is(", "nth-child(1 of "])
def test_nested_functions_and_chains_share_budget_on_small_worker_stack(
    function: str,
) -> None:
    for compounds in [96, 97]:
        chain = "i+" * (compounds - 1) + "x"
        query_in_subprocess(
            (":" + function) * 32 + chain + ")" * 32,
            "<i></i>" * (compounds - 1) + "<x></x>",
            1 if compounds == 96 else "matching complexity limit",
            worker=True,
        )


@pytest.mark.parametrize(("wrappers", "method"), [(0, "select"), (31, "select_one")])
def test_has_combines_maximum_html_and_selector_depth_on_small_worker_stack(
    wrappers: int, method: str
) -> None:
    # :has() recursively walks the tree in addition to recursing through the
    # selector. This used to exhaust tiny worker stacks even below both limits.
    compounds = 126 - wrappers
    html = (
        "<main>"
        + "<div>" * 254
        + "<i></i>" * (compounds - 1)
        + "<x></x>"
        + "</div>" * 254
        + "</main>"
    )
    for chain in ["i+" * (compounds - 1) + "x", "div>" * (compounds - 1) + "x"]:
        query_in_subprocess(
            ":is(" * wrappers + "main:has(" + chain + ")" * (wrappers + 1),
            html,
            1,
            method,
            worker=True,
        )


def test_wide_lists_and_long_compounds_do_not_consume_recursive_budget() -> None:
    document = parse('<p class="x" data-value="' + "(" * 256 + '"></p>')
    assert len(document.select(",".join(["p"] * 512))) == 1
    assert len(document.select(":is(" + ",".join(["p"] * 512) + ")")) == 1
    assert len(document.select(".x" * 512)) == 1
    assert len(document.select('[data-value="' + "(" * 256 + '"]')) == 1


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
        parse("<div><p></p></div>").select(selector)


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
def test_shadow_host_obeys_forgiving_selector_list_semantics(
    selector: str, tags: list[str]
) -> None:
    assert [
        element.tag for element in parse("<div><p></p></div>").select(selector)
    ] == tags


def test_host_text_in_strings_comments_and_identifiers_is_preserved() -> None:
    document = parse('<p data-value=":host(div)" class="host(foo)"></p>')
    for selector in ['[data-value=":host(div)"]', "p/*:host(div)*/", r".host\(foo\)"]:
        assert len(document.select(selector)) == 1
