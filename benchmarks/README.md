# Scraping benchmarks

The input is a captured UTF-8 response body in memory. A full scrape parses the
bytes, selects links and builds a Python list of `(href, descendant text)` pairs.
Astral takes a string, so its timed parse includes UTF-8 decoding. Lexbor, lxml
and Beautiful Soup receive the bytes directly. Disk and network I/O are outside
the timer.

| Snapshot | HTML bytes | All `a[href]` | Filtered links | Filter |
| --- | ---: | ---: | ---: | --- |
| PyPI package index | 6,144 | 16 | 8 | Downloads with a Python version requirement |
| GitHub file listing | 45,233 | 99 | 7 | File or directory names within the listing |
| Wikipedia article | 222,328 | 1,603 | 15 | Article links from paragraphs directly under the content container |

The runner checks the all-link and filtered counts above. Each timed extraction
must return the same ordered pairs as Lexbor on the decoded UTF-8 text,
including whitespace, non-ASCII characters, and duplicates.
The query on an existing tree uses the same filtered selector and string API
as the full scrape. Each library handles selector compilation and caching
through its public API. These fixed snapshots measure repeated scraping of
three pages with different sizes and match counts. Parsers can produce
different trees on other pages, particularly when the HTML is malformed.

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

The recorded Linux runs pinned each worker to one logical CPU. Set `cpu` to
a CPU allowed on your machine (`taskset -pc $$` lists them). The timing run
also works without `taskset`. The RSS run requires Linux with glibc.

```sh
cpu=0
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

The release wheel used the parser sources at `da95d37` (0.1.0), Rust 1.99.0 and
maturin 1.15.0. We ran on a Linux x86-64 AMD EPYC Milan VM with glibc 2.39
and CPython 3.14.8. Other libraries were selectolax 1.0.0 (Lexbor), lxml
6.1.3 with cssselect 1.5.0, and Beautiful Soup 4.15.0 with its lxml backend.

| Page | Parser | Parse | Parse + all links | Parse + filtered links | Filtered on existing tree |
| --- | --- | ---: | ---: | ---: | ---: |
| PyPI | astral-html | 8.51 ± 0.05 | 14.8 ± 0.08 | 13.3 ± 0.2 | 3.93 ± 0.02 |
| PyPI | selectolax (Lexbor) | 55.9 ± 1 | 85.4 ± 0.7 | 81.3 ± 0.8 | 8.24 ± 0.05 |
| PyPI | lxml | 56.1 ± 0.6 | 167 ± 3 | 162 ± 2 | 80.6 ± 2 |
| PyPI | Beautiful Soup | 768 ± 20 | 909 ± 7 | 943 ± 20 | 117 ± 0.9 |
| GitHub | astral-html | 240 ± 20 | 258 ± 1 | 268 ± 20 | 20.7 ± 0.08 |
| GitHub | selectolax (Lexbor) | 345 ± 4 | 465 ± 20 | 391 ± 1 | 27.8 ± 1 |
| GitHub | lxml | 955 ± 8 | 1,330 ± 6 | 1,180 ± 2 | 169 ± 5 |
| GitHub | Beautiful Soup | 12,000 ± 80 | 13,300 ± 90 | 14,100 ± 80 | 1,870 ± 30 |
| Wikipedia | astral-html | 1,140 ± 20 | 1,610 ± 5 | 1,510 ± 9 | 361 ± 4 |
| Wikipedia | selectolax (Lexbor) | 1,890 ± 20 | 2,910 ± 50 | 2,160 ± 30 | 214 ± 2 |
| Wikipedia | lxml | 4,450 ± 10 | 8,780 ± 40 | 5,930 ± 60 | 1,310 ± 7 |
| Wikipedia | Beautiful Soup | 81,900 ± 400 | 90,300 ± 300 | 110,000 ± 1,000 | 26,900 ± 300 |

The project README plots the **Parse + filtered links** column. Each page has
its own zero-based time axis. Bars show the mean in microseconds and whiskers
span one standard error on either side. To redraw the chart from the
[recorded means and standard errors](filtered-links.json), run
`uv run --script benchmarks/plot.py` from the repository root.

Retaining only `a` subtrees and extracting all links took 14.5 ± 0.2 µs on
PyPI, 233 ± 1 µs on GitHub, and 1,520 ± 20 µs on Wikipedia. The filtered
selectors rely on ancestors dropped by partial parsing.

## Retained memory

Each cell is the incremental RSS in KiB per live document, mean ± standard error
across seven fresh processes per mode. Each process warms the parser, takes a
baseline with the decoded input already in memory, and retains 64 parses of
that input. The runner collects garbage and calls glibc’s `malloc_trim` before
each RSS reading. Full and partial runs alternate order.

| Page | Full tree | Link subtrees |
| --- | ---: | ---: |
| PyPI | 15.1 ± 0.01 | 9.79 ± 0.01 |
| GitHub | 134 ± 0 | 39.6 ± 0 |
| Wikipedia | 724 ± 0 | 295 ± 0 |

A zero standard error means all seven readings agreed at the OS reporting
resolution. The absolute RSS values depend on the allocator and process history.

## Fixture sources

[HTML snapshots](fixtures/) are unchanged from [astral-html at b363c5e](https://github.com/astral-sh/astral-html/tree/b363c5e79fb5b896d5ac7b7bd78786fd5e9d196c).
The [PyPI page](https://github.com/astral-sh/astral-tl/blob/04bbd94a054e164a3d057160977197ca25194bc5/benches/tl.rs)
came via [astral-tl](fixtures/LICENSE-astral-tl), the [GitHub and Wikipedia pages](https://github.com/inikulin/parse5/tree/e65eae9a9dc27f1b7eb71868d245ca83070ccc4a/test/data/location-info)
via [parse5](fixtures/LICENSE-parse5). Page content retains its original terms,
including [Wikipedia contributors’ revision 592782173](https://en.wikipedia.org/w/index.php?title=42_(number)&oldid=592782173)
under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/).
