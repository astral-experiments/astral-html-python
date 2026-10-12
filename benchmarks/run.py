"""Benchmark real scraping tasks with equivalent output across parsers.

Run from the repository root with ``uv run --group benchmark python benchmarks/run.py``.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import platform
import random
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from importlib.metadata import version
from pathlib import Path
from typing import Any

import astral_html
from bs4 import BeautifulSoup
from lxml import html
from selectolax.lexbor import LexborHTMLParser

# Python may use safe-path mode, which excludes the script directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from formatting import format_measurement

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@dataclass(frozen=True)
class Fixture:
    name: str
    filename: str
    filtered_selector: str


FIXTURE_SET = (
    Fixture("PyPI", "iniconfig.html", "body > a[data-requires-python]"),
    Fixture("GitHub", "github-parse5.html", "table.files tr > td.content a[href]"),
    Fixture("Wikipedia", "wiki-42.html", '#mw-content-text > p a[href^="/wiki/"]'),
)


@dataclass(frozen=True)
class Parser:
    name: str
    parse: Callable[[str], Any]
    extract: Callable[[Any, str], list[tuple[str | None, str]]]


def astral_extract(document: Any, selector: str) -> list[tuple[str | None, str]]:
    return [
        (element.get("href"), element.text) for element in document.select(selector)
    ]


def lexbor_extract(document: Any, selector: str) -> list[tuple[str | None, str]]:
    return [
        (
            element.attrs.get("href"),
            element.text(deep=True, separator="", strip=False),
        )
        for element in document.css(selector)
    ]


def lxml_extract(document: Any, selector: str) -> list[tuple[str | None, str]]:
    return [
        (element.get("href"), element.text_content())
        for element in document.cssselect(selector)
    ]


def soup_extract(document: Any, selector: str) -> list[tuple[str | None, str]]:
    return [
        (element.get("href"), element.get_text())
        for element in document.select(selector)
    ]


PARSERS = (
    Parser("astral-html", astral_html.parse, astral_extract),
    Parser("selectolax (Lexbor)", LexborHTMLParser, lexbor_extract),
    Parser("lxml", html.fromstring, lxml_extract),
    Parser(
        "Beautiful Soup (lxml)",
        lambda source: BeautifulSoup(source, "lxml"),
        soup_extract,
    ),
)


def measure_batch(operation: Callable[[], object], min_sample_time: float) -> float:
    """Measure a calibrated batch in microseconds per operation."""
    # A short warmup also amortizes one-time selector/parser initialization.
    for _ in range(3):
        operation()

    iterations = 1
    while True:
        start = time.perf_counter_ns()
        for _ in range(iterations):
            operation()
        elapsed = (time.perf_counter_ns() - start) / 1e9
        if elapsed >= min_sample_time:
            break
        iterations *= 2

    # Keep GC enabled during the sample, and start each batch in a comparable state.
    gc.collect()
    start = time.perf_counter_ns()
    for _ in range(iterations):
        operation()
    return (time.perf_counter_ns() - start) / iterations / 1_000


def check_equal(label: str, expected: object, actual: object) -> None:
    if actual != expected:
        raise ValueError(
            f"{label} did not return the reference extraction; refusing to benchmark"
        )


def operations(
    parser: Parser, source: str, selector: str, document: Any
) -> tuple[tuple[str, Callable[[], object]], ...]:
    def parse_op() -> object:
        return parser.parse(source)

    def links_op() -> object:
        return parser.extract(parser.parse(source), "a[href]")

    def filtered_op() -> object:
        return parser.extract(parser.parse(source), selector)

    def query_op() -> object:
        return parser.extract(document, selector)

    return (
        ("Parse", parse_op),
        ("Parse + links", links_op),
        ("Parse + filtered CSS", filtered_op),
        ("Filtered CSS on existing tree", query_op),
    )


def partial_links(source: str) -> object:
    return astral_extract(astral_html.parse(source, tags=["a"]), "a[href]")


def sample(
    fixture: Fixture, min_sample_time: float, seed: int
) -> list[tuple[str, str, float]]:
    """Measure every workload once in this process, in a shuffled order."""
    source = (FIXTURES / fixture.filename).read_bytes().decode("utf-8")
    selectors = ("a[href]", fixture.filtered_selector)
    documents = {parser.name: parser.parse(source) for parser in PARSERS}
    lexbor = PARSERS[1]
    expected = {
        selector: lexbor.extract(documents[lexbor.name], selector)
        for selector in selectors
    }
    for parser in PARSERS:
        for selector in selectors:
            check_equal(
                f"{fixture.name}, {parser.name}, {selector}",
                expected[selector],
                parser.extract(documents[parser.name], selector),
            )
    check_equal(
        f"{fixture.name}, partial parse",
        expected["a[href]"],
        astral_extract(astral_html.parse(source, tags=["a"]), "a[href]"),
    )

    cases = [
        (label, parser.name, operation)
        for parser in PARSERS
        for label, operation in operations(
            parser, source, fixture.filtered_selector, documents[parser.name]
        )
    ]
    cases.append(
        ("Partial parse + links", "astral-html", partial(partial_links, source))
    )
    order = list(range(len(cases)))
    random.Random(seed).shuffle(order)
    timings = [0.0] * len(cases)
    for index in order:
        timings[index] = measure_batch(cases[index][2], min_sample_time)
    return [
        (label, parser_name, timing)
        for (label, parser_name, _), timing in zip(cases, timings, strict=True)
    ]


def run(samples: int, min_sample_time: float, fixture_names: set[str]) -> None:
    print(f"Python {platform.python_version()}")
    print(
        "Versions: "
        + ", ".join(
            f"{package} {version(package)}"
            for package in (
                "astral-html-python",
                "selectolax",
                "lxml",
                "cssselect",
                "beautifulsoup4",
            )
        )
    )
    print(
        f"\n{samples} fresh process samples per result, "
        f"batches calibrated to at least {min_sample_time * 1000:g} ms."
    )
    print("Mean (SE), µs/operation; lower is better.\n")
    print("| Fixture | Workload | Parser | Mean (SE), µs |")
    print("| --- | --- | --- | ---: |")

    for fixture in FIXTURE_SET:
        if fixture_names and fixture.name.lower() not in fixture_names:
            continue
        timings: dict[tuple[str, str], list[float]] = {}
        for seed in range(samples):
            print(
                f"{fixture.name}: sample {seed + 1}/{samples}",
                file=sys.stderr,
                flush=True,
            )
            worker = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--worker",
                    fixture.name.lower(),
                    "--seed",
                    str(seed),
                    "--min-sample-ms",
                    str(min_sample_time * 1000),
                ],
                check=True,
                stdout=subprocess.PIPE,
                text=True,
            )
            for label, parser_name, elapsed in json.loads(worker.stdout):
                timings.setdefault((label, parser_name), []).append(elapsed)
        for (label, parser_name), values in timings.items():
            mean = statistics.mean(values)
            error = statistics.stdev(values) / math.sqrt(samples)
            print(
                f"| {fixture.name} | {label} | {parser_name} | {format_measurement(mean, error)} |",
                flush=True,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--samples",
        type=int,
        default=20,
        help="fresh process samples (default: 20)",
    )
    parser.add_argument(
        "--min-sample-ms",
        type=float,
        default=20,
        help="minimum calibration batch time in ms",
    )
    parser.add_argument(
        "--fixture",
        choices=[fixture.name.lower() for fixture in FIXTURE_SET],
        action="append",
    )
    parser.add_argument(
        "--worker",
        choices=[fixture.name.lower() for fixture in FIXTURE_SET],
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--seed", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if (
        args.samples < 2
        or not math.isfinite(args.min_sample_ms)
        or args.min_sample_ms <= 0
    ):
        parser.error(
            "--samples must be at least 2 and --min-sample-ms must be positive"
        )
    if args.worker:
        fixture = next(f for f in FIXTURE_SET if f.name.lower() == args.worker)
        print(json.dumps(sample(fixture, args.min_sample_ms / 1000, args.seed)))
    else:
        run(args.samples, args.min_sample_ms / 1000, set(args.fixture or []))


if __name__ == "__main__":
    main()
