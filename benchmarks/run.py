"""Compare scraping time, or retained RSS with --memory (Linux/glibc)."""

import argparse
import ctypes
import gc
import math
import multiprocessing
import platform
import random
from collections import defaultdict
from functools import partial
from importlib.metadata import version
from pathlib import Path
from statistics import mean, stdev
from timeit import Timer

import astral_html
from bs4 import BeautifulSoup
from lxml import html
from selectolax.lexbor import LexborHTMLParser

FIXTURES = {
    # Each pair pins the published all-link and filtered-link counts.
    "pypi": ("iniconfig.html", "body > a[data-requires-python]", (16, 8)),
    "github": ("github-parse5.html", "table.files tr > td.content a[href]", (99, 7)),
    "wikipedia": ("wiki-42.html", '#mw-content-text > p a[href^="/wiki/"]', (1603, 15)),
}
ALL_LINKS = "a[href]"


def lexbor_links(doc, css):
    return [(node.attrs.get("href"), node.text()) for node in doc.css(css)]


def astral_links(doc, css):
    return [(node.get("href"), node.text) for node in doc.select(css)]


def lxml_links(doc, css):
    return [(node.get("href"), node.text_content()) for node in doc.cssselect(css)]


def soup_links(doc, css):
    return [(node.get("href"), node.get_text()) for node in doc.select(css)]


PARSERS = [
    ("astral-html", lambda raw: astral_html.parse(raw.decode("utf-8")), astral_links),
    ("selectolax (Lexbor)", LexborHTMLParser, lexbor_links),
    ("lxml", html.fromstring, lxml_links),
    ("Beautiful Soup", partial(BeautifulSoup, features="lxml"), soup_links),
    (
        "astral-html partial",
        lambda raw: astral_html.parse(raw.decode("utf-8"), tags=["a"]),
        astral_links,
    ),
]


def parse_and_extract(read, links, css):
    return links(read(), css)


def workloads(source, filtered_css, counts):
    reference = LexborHTMLParser(source.decode("utf-8"))
    expected = {}
    for css, count in zip((ALL_LINKS, filtered_css), counts, strict=True):
        pairs = lexbor_links(reference, css)
        if len(pairs) != count:
            raise ValueError(f"{css!r}: expected {count} links, found {len(pairs)}")
        expected[css] = pairs
    jobs = []
    for name, parse, links in PARSERS:
        read = partial(parse, source)
        extract = partial(parse_and_extract, read, links)
        queries = [("parse + all links", extract, ALL_LINKS)]
        # Filtered selectors need ancestors discarded by partial parsing.
        if name != "astral-html partial":
            jobs.append((f"{name} | parse", read))
            existing = partial(links, read())
            queries.extend(
                [
                    ("parse + filtered links", extract, filtered_css),
                    ("filtered links, existing tree", existing, filtered_css),
                ]
            )
        for label, query, css in queries:
            run = partial(query, css)
            if run() != expected[css]:
                raise ValueError(f"{name}: {css!r} links differ from Lexbor's")
            jobs.append((f"{name} | {label}", run))
    return jobs


def timings(source, selector, counts, min_ms, seed):
    jobs = workloads(source, selector, counts)  # Check all outputs before timing.
    times = dict.fromkeys((label for label, _ in jobs), 0.0)
    random.Random(seed).shuffle(jobs)
    target = min_ms / 1000
    for label, run in jobs:
        # Timer normally disables GC. Keep it enabled, including for cyclic trees.
        timer = Timer(run, setup=gc.enable)
        gc.collect()
        # Repeated parses let automatic GC reclaim cycles during the batch.
        count = 8
        while timer.timeit(count) < target:
            count *= 2
        times[label] = timer.timeit(count) * 1e6 / count
    return times


def rss_kib():
    gc.collect()
    ctypes.CDLL(None).malloc_trim(0)
    status = Path("/proc/self/status").read_text()
    return int(status.split("VmRSS:")[1].split()[0])


def memory(source, mode):
    parse = partial(astral_html.parse, tags=["a"] if mode == "partial" else None)
    parse(source)  # Exclude parser initialization and the input from the baseline.
    before = rss_kib()
    documents = [parse(source) for _ in range(64)]
    return {f"astral-html | {mode}": (rss_kib() - before) / len(documents)}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--fixture", choices=FIXTURES, action="append")
    cli.add_argument(
        "--samples", type=int, help="fresh processes (default 20, or 7 for RSS)"
    )
    mode = cli.add_mutually_exclusive_group()
    mode.add_argument("--memory", action="store_true", help="RSS per retained document")
    mode.add_argument(
        "--check", action="store_true", help="check outputs without timing"
    )
    cli.add_argument("--min-sample-ms", type=float, default=20)
    args = cli.parse_args()
    n = (7 if args.memory else 20) if args.samples is None else args.samples
    if n < 2 or not math.isfinite(args.min_sample_ms) or args.min_sample_ms <= 0:
        cli.error("need at least two samples and a positive, finite batch time")

    packages = [
        "astral-html-python",
        "selectolax",
        "lxml",
        "cssselect",
        "beautifulsoup4",
    ]
    versions = ", ".join(f"{p} {version(p)}" for p in packages)
    print(f"Python {platform.python_version()}, {versions}")
    unit = "KiB/document" if args.memory else "µs"
    if not args.check:
        print(f"\n| Fixture | Parser | Workload | Mean ± SE ({unit}, {n} processes) |")
        print("| --- | --- | --- | ---: |")
    for page in args.fixture or FIXTURES:
        filename, selector, counts = FIXTURES[page]
        source = (Path(__file__).parent / "fixtures" / filename).read_bytes()
        if args.check:
            workloads(source, selector, counts)
            print(f"{page}: all extraction outputs match Lexbor")
            continue
        if args.memory:
            worker = partial(memory, source.decode("utf-8"))
            modes = ("full", "partial")
            jobs = [m for i in range(n) for m in (modes[::-1] if i % 2 else modes)]
        else:
            worker = partial(timings, source, selector, counts, args.min_sample_ms)
            jobs = range(n)
        values = defaultdict(list)
        with multiprocessing.get_context("spawn").Pool(1, maxtasksperchild=1) as pool:
            for sample in pool.imap(worker, jobs):
                for label, value in sample.items():
                    values[label].append(value)
        for label, v in values.items():
            print(
                f"| {page} | {label} | {mean(v):.3g} ± {stdev(v) / math.sqrt(n):.1g} |",
                flush=True,
            )


if __name__ == "__main__":
    main()
