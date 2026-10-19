import gc
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from astral_html import Element, parse


@pytest.mark.parametrize("tags", [None, ["main"]])
def test_element_identity_across_queries_and_traversal(tags: list[str] | None) -> None:
    document = parse("<main><i>same</i><i>same</i></main>", tags=tags)
    (main,) = document.elements("main")
    first, second = main.children
    aliases = [
        document.select_one("i"),
        document.select("i")[0],
        document.elements("i")[0],
        main.select_one("i"),
        main.select("i")[0],
        main.elements("i")[0],
    ]
    for alias in aliases:
        assert alias == first
        assert not (alias != first)  # noqa: SIM202 - exercise inequality too
        assert {first: "found"}[alias] == "found"
    assert first.parent == main
    assert first != second
    assert len({first, second}) == 2
    with pytest.raises(TypeError):
        _ = first < second  # ty: ignore[unsupported-operator]


def test_comparisons_delegate_to_the_other_operand() -> None:
    class Other:
        def __eq__(self, other: object) -> bool:
            return True

        def __ne__(self, other: object) -> bool:
            return True

    (element,) = parse("<i>").elements("i")
    assert element == Other()
    assert (element != Other()) is True


@pytest.mark.parametrize("tags", [None, ["i"]])
def test_element_identity_is_per_parse_and_outlives_document(
    tags: list[str] | None,
) -> None:
    source = '<main><i data-url="/café">Café &amp; tea <b>too</b></i></main>'
    document = parse(source, tags=tags)
    (element,) = document.elements("i")
    (alias,) = document.elements("i")
    (other,) = parse(source, tags=tags).elements("i")
    assert element != other
    assert len({element, alias, other}) == 2
    before = hash(element)
    del document, source
    gc.collect()
    assert element == alias
    assert hash(element) == hash(alias) == before
    assert element.get("data-url") == "/café"
    assert element.text == "Café & tea too"
    assert element.select_one("b") is not None


def test_shared_tree_queries_from_multiple_threads() -> None:
    document = parse("<main>" + "<i><b>text</b></i>" * 20 + "</main>")
    (main,) = document.elements("main")

    def query(_: int) -> tuple[list[Element], list[Element]]:
        return document.select("i > b"), main.select("i > b")

    expected = document.select("b")
    with ThreadPoolExecutor(max_workers=4) as executor:
        for document_result, element_result in executor.map(query, range(24)):
            assert document_result == element_result == expected


@pytest.mark.parametrize("element_scope", [False, True])
@pytest.mark.parametrize("method", ["elements", "select", "select_one"])
def test_tree_queries_release_gil(element_scope: bool, method: str) -> None:
    document = parse("<main>" + '<i class="present"></i>' * 20_000 + "</main>")
    scope = document.elements("main")[0] if element_scope else document
    query = getattr(scope, method)
    argument = "absent" if method == "elements" else 'i[class~="absent"]'
    ready = threading.Event()
    querying = observed = done = False

    def observe() -> None:
        nonlocal observed
        ready.set()
        while not done:
            if querying:
                observed = True
                return
            time.sleep(0)

    observer = threading.Thread(target=observe)
    observer.start()
    previous_interval = sys.getswitchinterval()
    try:
        assert ready.wait(timeout=10)
        # Prevent bytecode switches so the observer must run during a native
        # query. Retry instead of assuming it runs on the first OS timeslice.
        sys.setswitchinterval(60)
        for _ in range(1_000):
            querying = True
            result = query(argument)
            querying = False
            assert result == (None if method == "select_one" else [])
            if observed:
                break
        assert observed, "Python observer could not run during matching"
    finally:
        done = True
        sys.setswitchinterval(previous_interval)
        observer.join(timeout=10)
    assert not observer.is_alive()
