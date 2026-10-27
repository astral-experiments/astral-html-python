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

Each timed extraction must return the same ordered pairs as Lexbor on the
known UTF-8 text, including whitespace, non-ASCII characters, and duplicates.
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
worker processes per page. Each worker shuffles the jobs, calibrates a batch
against a 12 ms target and measures one batch of that fixed size. Cyclic GC is
enabled. Parsing and full scrapes create a new tree each iteration. The last
column reuses one parsed document.

The release wheel used parser revision `4ba2c2f` (0.1.0), Rust 1.99.0 and
maturin 1.15.0. We ran on a Linux x86-64 AMD EPYC Milan VM with glibc 2.39
and CPython 3.14.8. Other libraries were selectolax 1.0.0 (Lexbor), lxml
6.1.3 with cssselect 1.5.0, and Beautiful Soup 4.15.0 with its lxml backend.

| Page | Parser | Parse | Parse + all links | Parse + filtered links | Filtered on existing tree |
| --- | --- | ---: | ---: | ---: | ---: |
| PyPI | astral-html | 8.51 ± 0.04 | 14.8 ± 0.09 | 13.3 ± 0.08 | 4.12 ± 0.1 |
| PyPI | selectolax (Lexbor) | 53.6 ± 3 | 86.3 ± 5 | 77.1 ± 4 | 8.3 ± 0.09 |
| PyPI | lxml | 58.8 ± 2 | 167 ± 2 | 170 ± 5 | 78.2 ± 0.6 |
| PyPI | Beautiful Soup | 734 ± 6 | 890 ± 10 | 908 ± 7 | 119 ± 0.9 |
| GitHub | astral-html | 234 ± 10 | 262 ± 2 | 249 ± 2 | 20.5 ± 0.08 |
| GitHub | selectolax (Lexbor) | 344 ± 0.9 | 450 ± 2 | 415 ± 20 | 26.6 ± 0.1 |
| GitHub | lxml | 952 ± 5 | 1,340 ± 10 | 1,180 ± 3 | 167 ± 2 |
| GitHub | Beautiful Soup | 11,200 ± 40 | 12,400 ± 100 | 13,500 ± 400 | 1,830 ± 7 |
| Wikipedia | astral-html | 1,140 ± 9 | 1,650 ± 20 | 1,510 ± 7 | 358 ± 2 |
| Wikipedia | selectolax (Lexbor) | 1,900 ± 20 | 2,910 ± 20 | 2,130 ± 10 | 229 ± 7 |
| Wikipedia | lxml | 4,540 ± 30 | 9,050 ± 100 | 5,930 ± 40 | 1,330 ± 10 |
| Wikipedia | Beautiful Soup | 61,700 ± 300 | 72,600 ± 1,000 | 88,600 ± 300 | 27,000 ± 200 |

Retaining only `a` subtrees and extracting all links took 14.4 ± 0.1 µs on
PyPI, 236 ± 2 µs on GitHub, and 1,570 ± 40 µs on Wikipedia. The filtered
selectors rely on ancestors dropped by partial parsing.

## Retained memory

Each cell is the incremental RSS in KiB per live document, mean ± standard error
across seven fresh processes per mode. Each process warms the parser, takes a
baseline with the decoded input already in memory, and retains 64 parses of
that input. The runner collects garbage and calls glibc’s `malloc_trim` before
each RSS reading. Full and partial runs alternate order.

| Page | Full tree | Link subtrees |
| --- | ---: | ---: |
| PyPI | 15.1 ± 0.01 | 9.81 ± 0 |
| GitHub | 133 ± 0.3 | 38.9 ± 0 |
| Wikipedia | 723 ± 0 | 296 ± 0.1 |

A zero standard error means all seven readings agreed at the OS reporting
resolution. The absolute RSS values depend on the allocator and process history.

## Fixture sources

[HTML snapshots](fixtures/) are unchanged from [astral-html at b363c5e](https://github.com/astral-sh/astral-html/tree/b363c5e79fb5b896d5ac7b7bd78786fd5e9d196c).
The [PyPI page](https://github.com/astral-sh/astral-tl/blob/04bbd94a054e164a3d057160977197ca25194bc5/benches/tl.rs)
came via [astral-tl](fixtures/LICENSE-astral-tl), the [GitHub and Wikipedia pages](https://github.com/inikulin/parse5/tree/e65eae9a9dc27f1b7eb71868d245ca83070ccc4a/test/data/location-info)
via [parse5](fixtures/LICENSE-parse5). Page content retains its original terms,
including [Wikipedia contributors’ revision 592782173](https://en.wikipedia.org/w/index.php?title=42_(number)&oldid=592782173)
under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/).
