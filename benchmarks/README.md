# Scraping benchmarks

Each full scrape starts with a saved UTF-8 response body in memory and ends
with a Python list of `(href, descendant text)` pairs. It includes parsing,
CSS selection, and extraction. The astral-html-python API takes a string, so
its timed parse includes UTF-8 decoding. The other parsers receive the bytes
directly. Disk and network I/O are outside the timer.

The three snapshots below exercise page-specific selectors. A separate
benchmark compares link extraction on 1,867 distinct HTML bodies across seven page
types. [Large-corpus benchmark](wcxb.md)

We also compared native and stable-ABI wheels on 140 pages using CPython 3.14
and 3.15. [Wheel ABI comparison](https://github.com/astral-experiments/astral-html-python/blob/d52265197b7bcc11f43afcab280e5e5306d20c61/results/wheel-abi/wheel-abi.md)

| Snapshot | HTML bytes | All `a` | All `a[href]` | Filtered links | Filtered CSS selector |
| --- | ---: | ---: | ---: | ---: | --- |
| PyPI package index | 6,144 | 16 | 16 | 8 | `body > a[data-requires-python]` |
| GitHub file listing | 45,233 | 99 | 99 | 7 | `table.files tr > td.content a[href]` |
| Wikipedia article | 222,328 | 1,604 | 1,603 | 15 | `#mw-content-text > p a[href^="/wiki/"]` |

Before timing, the runner checks the counts and compares each extraction
against Lexbor's output on the decoded UTF-8 text. The pairs must match in
order and preserve whitespace, non-ASCII characters, and duplicates. Parsers
can produce different trees on other pages, particularly when the HTML is
malformed.

The existing-tree workloads parse once, then repeat selection and extraction
with either the bare `a` selector or the page-specific selector. Both return
ordered `(href, text)` pairs. The Wikipedia page includes one anchor without an
`href`, which contributes `None` in the bare-tag workload. Each library handles
selector compilation and caching through its public API. [Benchmark runner](run.py)

## Reproduce

From the repository root, build a release wheel from the source distribution
and install it alongside the locked benchmark dependencies.

```sh
uv sync --locked --python 3.14 --group benchmark --no-install-project
dist=$(mktemp -d)
uv build --no-sources --out-dir "$dist" --python .venv/bin/python \
    --config-setting 'build-args=--compatibility pypi --auditwheel check'
uv pip install --python .venv/bin/python --no-deps --reinstall "$dist"/*.whl
.venv/bin/python -I benchmarks/run.py --check
```

The recorded Linux runs pinned each worker to one logical CPU. The example
below selects the first CPU available to the current process. You can also
run the timings without `taskset`. The RSS run requires Linux with glibc.

```sh
cpu=$(.venv/bin/python -c 'import os; print(min(os.sched_getaffinity(0)))')
taskset -c "$cpu" .venv/bin/python -I benchmarks/run.py --samples 12 --min-sample-ms 12
taskset -c "$cpu" .venv/bin/python -I benchmarks/run.py --memory --samples 7
```

## Time per operation

Results are microseconds per operation, mean ± standard error across 12 fresh
worker processes per page. Each worker shuffles the jobs and calibrates
a batch of at least eight operations against a 12 ms target. It then measures
another batch of that size with cyclic GC enabled throughout both batches.
Parsing and full scrapes create a new tree each iteration. Automatic collection
can reclaim earlier trees during timing. Any cleanup after the measured batch
is outside the timer. The last column reuses one parsed document.

We measured astral-html-python 0.0.1 on a GitHub-hosted x86_64 runner with
Ubuntu 24.04.5 LTS and an AMD EPYC 7763 64-Core Processor. We pinned the
workers to logical CPU 0. We built the release wheel from the source
distribution with Rust 1.99.0 and maturin 1.15.0. The run used CPython 3.14.9
and glibc 2.39. The other libraries were selectolax 1.0.0 (Lexbor), lxml 6.1.3
with cssselect 1.5.0, and Beautiful Soup 4.15.0 with its lxml backend.
[Parser and runner revision `98a6a38`](https://github.com/astral-experiments/astral-html-python/tree/98a6a38dcc5e3f85e77a11139e38927d511430a4) ·
[Measurement run](https://github.com/astral-experiments/astral-html-python/actions/runs/40938603187)

| Page | Parser | Parse | Parse + all links | Parse + filtered links | Filtered on existing tree |
| --- | --- | ---: | ---: | ---: | ---: |
| PyPI | astral-html | 9.16 ± 0.8 | 14.8 ± 0.09 | 13.2 ± 0.07 | 4.28 ± 0.03 |
| PyPI | selectolax (Lexbor) | 23.3 ± 0.2 | 43.1 ± 0.2 | 37.8 ± 0.1 | 9.78 ± 0.3 |
| PyPI | lxml | 54.6 ± 0.3 | 177 ± 2 | 168 ± 0.8 | 91.6 ± 0.3 |
| PyPI | Beautiful Soup | 949 ± 3 | 1,120 ± 4 | 1,150 ± 6 | 148 ± 0.7 |
| GitHub | astral-html | 207 ± 2 | 260 ± 10 | 235 ± 2 | 22.3 ± 0.1 |
| GitHub | selectolax (Lexbor) | 331 ± 0.8 | 450 ± 4 | 375 ± 0.9 | 27.6 ± 0.2 |
| GitHub | lxml | 895 ± 2 | 1,340 ± 8 | 1,150 ± 9 | 178 ± 0.5 |
| GitHub | Beautiful Soup | 16,500 ± 400 | 17,400 ± 60 | 18,400 ± 70 | 2,170 ± 10 |
| Wikipedia | astral-html | 1,090 ± 4 | 1,570 ± 3 | 1,470 ± 4 | 394 ± 10 |
| Wikipedia | selectolax (Lexbor) | 1,810 ± 10 | 3,020 ± 8 | 2,050 ± 5 | 215 ± 1 |
| Wikipedia | lxml | 4,230 ± 10 | 9,170 ± 20 | 5,450 ± 60 | 1,110 ± 2 |
| Wikipedia | Beautiful Soup | 104,000 ± 300 | 115,000 ± 600 | 137,000 ± 500 | 32,500 ± 100 |

The project README plots the **Parse + filtered links** column. Each page has
its own zero-based time axis. Bars show the mean in microseconds and whiskers
span one standard error on either side. To redraw the chart from the
[recorded means and standard errors](filtered-links.json), run
`uv run --script benchmarks/plot.py` from the repository root.

Retaining only `a` subtrees and extracting all links took 14.1 ± 0.06 µs on
PyPI, 222 ± 2 µs on GitHub, and 1,460 ± 5 µs on Wikipedia. The filtered
selectors rely on ancestors dropped by partial parsing.

## All anchors on an existing tree

These timings cover selecting `a` on a parsed page and reading each anchor’s
`href` and descendant text. Both Astral modes use `doc.select("a")`.
The partial tree was built with `parse(html, retain_subtrees="a")`.

| Parser | PyPI (µs) | GitHub (µs) | Wikipedia (µs) |
| --- | ---: | ---: | ---: |
| astral-html | 5.45 ± 0.04 | 28.7 ± 0.08 | 445 ± 2 |
| astral-html, link subtrees | 5.45 ± 0.06 | 26.7 ± 0.09 | 429 ± 2 |
| selectolax (Lexbor) | 14.4 ± 0.08 | 87.8 ± 0.4 | 1,180 ± 3 |
| lxml | 66 ± 0.3 | 333 ± 1 | 4,680 ± 8 |
| Beautiful Soup | 113 ± 0.4 | 1,130 ± 3 | 9,520 ± 30 |

Values are means ± one standard error from the same 12 worker processes per
page as the full-scrape timings. Look for the `all anchors, existing tree`
rows in the runner output.

## Retained memory

Each cell is the incremental RSS in KiB per live document, mean ± standard error
across seven fresh processes per mode. Each process warms the parser, takes a
baseline with the decoded input already in memory, and retains 64 parses of
that input. The runner collects garbage and calls glibc’s `malloc_trim` before
each RSS reading. Full and partial runs alternate order.

| Page | Full tree | Link subtrees |
| --- | ---: | ---: |
| PyPI | 14.1 ± 0 | 8.75 ± 0 |
| GitHub | 133 ± 0.009 | 38.9 ± 0 |
| Wikipedia | 723 ± 0 | 295 ± 0 |

A zero standard error means all seven readings agreed at the OS reporting
resolution. The absolute RSS values depend on the allocator and process history.

## Fixture sources

The three HTML snapshots are unchanged from astral-html revision `b363c5e`.
[Local fixtures](fixtures/) · [Upstream fixtures](https://github.com/astral-sh/astral-html/tree/b363c5e79fb5b896d5ac7b7bd78786fd5e9d196c/crates/astral-html)

- The PyPI snapshot comes from the astral-tl benchmark.
  [Benchmark source](https://github.com/astral-sh/astral-tl/blob/04bbd94a054e164a3d057160977197ca25194bc5/benches/tl.rs) · [astral-tl license](fixtures/LICENSE-astral-tl)
- The GitHub and Wikipedia snapshots come from the parse5 test suite.
  [Original fixtures](https://github.com/inikulin/parse5/tree/e65eae9a9dc27f1b7eb71868d245ca83070ccc4a/test/data/location-info) · [parse5 license](fixtures/LICENSE-parse5)
- The page content retains its original terms. The Wikipedia snapshot credits
  the article's contributors and identifies its license as CC BY-SA 3.0.
  [Wikipedia revision 592782173](https://en.wikipedia.org/w/index.php?title=42_(number)&oldid=592782173) · [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/)
