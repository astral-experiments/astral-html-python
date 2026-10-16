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
    "pypi": ("iniconfig.html", "body > a[data-requires-python]"),
    "github": ("github-parse5.html", "table.files tr > td.content a[href]"),
    "wikipedia": ("wiki-42.html", '#mw-content-text > p a[href^="/wiki/"]'),
}


def lexbor_links(doc, css):
    return [(node.attrs.get("href"), node.text()) for node in doc.css(css)]


def astral_links(doc, css):
    return [(node.get("href"), node.text) for node in doc.select(css)]


def lxml_links(doc, css):
    return [(node.get("href"), node.text_content()) for node in doc.cssselect(css)]


def soup_links(doc, css):
    return [(node.get("href"), node.get_text()) for node in doc.select(css)]


PARSERS = [
    ("astral-html", astral_html.parse, astral_links),
    ("selectolax (Lexbor)", LexborHTMLParser, lexbor_links),
    ("lxml", html.fromstring, lxml_links),
    ("Beautiful Soup", partial(BeautifulSoup, features="lxml"), soup_links),
    ("astral-html partial", partial(astral_html.parse, tags=["a"]), astral_links),
]


def workloads(source, selector):
    queries = {"links": "a[href]", "filtered": selector}
    reference = LexborHTMLParser(source)
    expected = {css: lexbor_links(reference, css) for css in queries.values()}
    for name, parse, links in PARSERS:
        read = partial(parse, source)
        doc = read()
        for label, css in queries.items():
            if css == selector:
                if name == "astral-html partial":
                    continue  # The filtered selector needs ancestors we discarded.
                yield f"{name} | parse", read
                yield f"{name} | filtered, existing tree", partial(links, doc, css)
            if not expected[css] or links(doc, css) != expected[css]:
                raise ValueError(f"{name}: {css!r} links differ from Lexbor's")
            yield (
                f"{name} | parse + {label}",
                lambda read=read, links=links, css=css: links(read(), css),
            )


def timings(source, selector, min_ms, seed):
    jobs = list(workloads(source, selector))  # Check all outputs before timing.
    times = dict.fromkeys((label for label, _ in jobs), 0.0)
    random.Random(seed).shuffle(jobs)
    for label, run in jobs:
        # Timer normally disables GC. Keep it enabled, including for cyclic trees.
        timer = Timer(run, setup=gc.enable)
        count = 1
        while timer.timeit(count) < min_ms / 1000:
            count *= 2
        gc.collect()
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
    cli.add_argument("--memory", action="store_true", help="RSS per retained document")
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
    print(f"\n| Fixture | Parser | Workload | Mean ± SE ({unit}, {n} processes) |")
    print("| --- | --- | --- | ---: |")
    for page in args.fixture or FIXTURES:
        filename, selector = FIXTURES[page]
        source = (Path(__file__).parent / "fixtures" / filename).read_bytes().decode()
        if args.memory:
            worker = partial(memory, source)
            modes = ("full", "partial")
            jobs = [m for i in range(n) for m in (modes[::-1] if i % 2 else modes)]
        else:
            worker = partial(timings, source, selector, args.min_sample_ms)
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
