"""Compare scraping time, or retained RSS with --memory (Linux/glibc)."""

import argparse
import ctypes
import gc
import gzip
import hashlib
import math
import multiprocessing
import platform
import random
import tarfile
from collections import Counter, defaultdict
from functools import partial
from importlib.metadata import version
from pathlib import Path
from statistics import mean, stdev
from time import perf_counter_ns
from timeit import Timer

import astral_html
from bs4 import BeautifulSoup
from lxml import html
from selectolax.lexbor import LexborHTMLParser

FIXTURES = {
    # Counts for bare anchors, links with href, and the page-specific selector.
    "pypi": ("iniconfig.html", "body > a[data-requires-python]", (16, 16, 8)),
    "github": (
        "github-parse5.html",
        "table.files tr > td.content a[href]",
        (99, 99, 7),
    ),
    "wikipedia": (
        "wiki-42.html",
        '#mw-content-text > p a[href^="/wiki/"]',
        (1604, 1603, 15),
    ),
}
ALL_LINKS = "a[href]"
# Hash of the sorted SHA-256 digests of the distinct WCXB HTML bodies.
WCXB_DIGEST = "70cace552e1b71cd59d3203bbff239b4db54af10ad3d931c166f57b4e64cf3ec"


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
        lambda raw: astral_html.parse(raw.decode("utf-8"), retain_subtrees="a"),
        astral_links,
    ),
]


def parse_and_extract(read, links, css):
    return links(read(), css)


def workloads(source, filtered_css, counts):
    reference = LexborHTMLParser(source.decode("utf-8"))
    expected = {}
    for css, count in zip(("a", ALL_LINKS, filtered_css), counts, strict=True):
        pairs = lexbor_links(reference, css)
        if len(pairs) != count:
            raise ValueError(f"{css!r}: expected {count} links, found {len(pairs)}")
        expected[css] = pairs
    jobs = []
    for name, parse, links in PARSERS:
        read = partial(parse, source)
        extract = partial(parse_and_extract, read, links)
        existing = partial(links, read())
        queries = [
            ("parse + all links", extract, ALL_LINKS),
            ("all anchors, existing tree", existing, "a"),
        ]
        # Filtered selectors need ancestors discarded by partial parsing.
        if name != "astral-html partial":
            jobs.append((f"{name} | parse", read))
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
    parse = partial(
        astral_html.parse, retain_subtrees="a" if mode == "partial" else None
    )
    parse(source)  # Exclude parser initialization and the input from the baseline.
    before = rss_kib()
    documents = [parse(source) for _ in range(64)]
    return {f"astral-html | {mode}": (rss_kib() - before) / len(documents)}


def wcxb_pages(path):
    pages = {}
    with tarfile.open(path, "r|gz") as archive:
        for member in archive:
            parts = member.name.split("/")
            if (
                len(parts) != 4
                or parts[1] not in ("dev", "test")
                or parts[2] != "html"
                or not parts[3].endswith(".html.gz")
                or not member.isfile()
            ):
                continue
            stream = archive.extractfile(member)
            assert stream is not None
            body = gzip.decompress(stream.read())
            pages.setdefault(hashlib.sha256(body).digest(), ("/".join(parts[1:]), body))
    if hashlib.sha256(b"".join(sorted(pages))).hexdigest() != WCXB_DIGEST:
        raise ValueError("HTML bodies differ from the pinned WCXB corpus")
    return pages


def check_wcxb(path):
    pages = wcxb_pages(path)
    size = sum(len(body) for _, body in pages.values())
    print(f"{len(pages):,} distinct pages, {size:,} bytes")
    matching, differing = [], []
    agreements, rejected, counts = Counter(), Counter(), Counter()
    for key, (filename, body) in pages.items():
        outputs = {}
        for name, parse, links in PARSERS:
            try:
                outputs[name] = links(parse(body), ALL_LINKS)
            except ValueError as error:
                if str(error) != "HTML document exceeds the nesting limit":
                    raise
                print(f"{name} rejected {filename}: {error}", flush=True)
                rejected[name] += 1
        if outputs.get("astral-html") != outputs.get("astral-html partial"):
            raise ValueError(
                f"{filename}: partial-tree links differ from the full tree"
            )
        reference = outputs["selectolax (Lexbor)"]
        for name, pairs in outputs.items():
            agreements[name] += pairs == reference
            counts[name] += len(pairs)
        if len(outputs) == len(PARSERS):
            group = (
                matching
                if all(pairs == reference for pairs in outputs.values())
                else differing
            )
            group.append(key)
    print("| Parser | Pages matching Lexbor | Rejected pages | Extracted links |")
    print("| --- | ---: | ---: | ---: |")
    for name, _, _ in PARSERS:
        print(f"| {name} | {agreements[name]} | {rejected[name]} | {counts[name]} |")
    print(
        f"All parsers completed {len(matching) + len(differing)} pages. "
        f"Outputs were identical on {len(matching)}.",
        flush=True,
    )
    return matching, differing


def wcxb_sample(path, groups, seed):
    pages = wcxb_pages(path)
    rng = random.Random(seed)
    bodies = []
    for group in groups:
        batch = [pages[key][1] for key in sorted(group)]
        rng.shuffle(batch)
        bodies.append(batch)
    total = sum(map(len, bodies))
    times = {}
    # Rotate parser order across fresh processes. Every parser sees the same pages.
    start = seed % len(PARSERS)
    for name, parse, links in PARSERS[start:] + PARSERS[:start]:
        durations = [0, 0]
        for i in (seed % 2, 1 - seed % 2):
            batch = bodies[i]
            for body in batch[:5]:
                links(parse(body), ALL_LINKS)
            gc.collect()
            before = perf_counter_ns()
            for body in batch:
                links(parse(body), ALL_LINKS)
            durations[i] = perf_counter_ns() - before
        times[name] = (
            sum(durations) / total / 1000,
            durations[0] / len(bodies[0]) / 1000,
        )
    return times


def run_wcxb(path, samples, check_only):
    groups = check_wcxb(path)
    if check_only:
        return
    if not groups[0]:
        raise ValueError("No pages produced identical output across all parsers")
    worker = partial(wcxb_sample, path, groups)
    print(
        "\n| Sample | Parser | All completed (µs/page) | Identical output (µs/page) |"
    )
    print("| ---: | --- | ---: | ---: |")
    with multiprocessing.get_context("spawn").Pool(1, maxtasksperchild=1) as pool:
        runs = []
        for sample, times in enumerate(pool.imap(worker, range(samples)), 1):
            runs.append(times)
            for name, (all_pages, identical) in times.items():
                print(
                    f"| {sample} | {name} | {all_pages:.3f} | {identical:.3f} |",
                    flush=True,
                )
    print(
        "\n| Parser | All completed (µs/page ± SE) | Identical output (µs/page ± SE) |"
    )
    print("| --- | ---: | ---: |")
    for name, _, _ in PARSERS:
        cells = []
        for values in zip(*(run[name] for run in runs), strict=True):
            cells.append(
                f"{mean(values):.1f} ± {stdev(values) / math.sqrt(samples):.1f}"
            )
        print(f"| {name} | {' | '.join(cells)} |")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    inputs = cli.add_mutually_exclusive_group()
    inputs.add_argument("--fixture", choices=FIXTURES, action="append")
    inputs.add_argument(
        "--wcxb", type=Path, help="benchmark the pinned WCXB .tar.gz archive"
    )
    cli.add_argument(
        "--samples",
        type=int,
        help="fresh processes (default 20, 7 for RSS, or 10 for WCXB)",
    )
    mode = cli.add_mutually_exclusive_group()
    mode.add_argument("--memory", action="store_true", help="RSS per retained document")
    mode.add_argument(
        "--check", action="store_true", help="check outputs without timing"
    )
    cli.add_argument(
        "--min-sample-ms",
        type=float,
        help="batch target for fixed fixtures (default 20 ms)",
    )
    args = cli.parse_args()
    if args.samples is not None and args.samples < 2:
        cli.error("need at least two samples")
    if args.wcxb and (args.memory or args.min_sample_ms is not None):
        cli.error("--memory and --min-sample-ms apply only to fixed fixtures")
    min_ms = 20 if args.min_sample_ms is None else args.min_sample_ms
    if not math.isfinite(min_ms) or min_ms <= 0:
        cli.error("need a positive, finite batch time")

    packages = [
        "astral-html-python",
        "selectolax",
        "lxml",
        "cssselect",
        "beautifulsoup4",
    ]
    versions = ", ".join(f"{p} {version(p)}" for p in packages)
    print(f"Python {platform.python_version()}, {versions}")
    if args.wcxb:
        run_wcxb(args.wcxb, args.samples or 10, args.check)
        return
    n = args.samples or (7 if args.memory else 20)
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
            worker = partial(timings, source, selector, counts, min_ms)
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
