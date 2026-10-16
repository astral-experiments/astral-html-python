# Scraping benchmarks

```sh
uv run --group benchmark python benchmarks/run.py
uv run --group benchmark python benchmarks/run.py --memory  # Linux with glibc
```

Every parser must return Lexbor’s exact, ordered `(href, text)` pairs for all links and
for a page-specific query (PyPI downloads with Python requirements, GitHub files, or
Wikipedia article links). Parsers can still differ in how they recover malformed HTML.

## Time per operation, µs (mean ± standard error)

Release build of astral-html 0.1.0 on Python 3.14.8, with selectolax 1.0.0,
lxml 6.1.3, cssselect 1.5.0 and Beautiful Soup 4.15.0 (using lxml).
Each of 20 fresh processes shuffles the workloads and calibrates batches to at least
20 ms. Timing includes building the output, excludes file I/O, and leaves cyclic GC
enabled. “Query on tree” starts with a parsed document and uses each library’s normal
selector caching.

| Page | Parser | Parse | Parse + links | Parse + filtered | Query on tree |
| --- | --- | ---: | ---: | ---: | ---: |
| PyPI | astral-html | 7.74 ± 0.04 | 14.5 ± 0.1 | 12.9 ± 0.3 | 4.13 ± 0.03 |
| PyPI | selectolax | 62 ± 2 | 170 ± 10 | 170 ± 10 | 8.6 ± 0.1 |
| PyPI | lxml | 56.9 ± 0.3 | 163 ± 0.5 | 161 ± 1 | 78 ± 1 |
| PyPI | Beautiful Soup | 730 ± 20 | 930 ± 70 | 900 ± 30 | 116 ± 0.9 |
| GitHub | astral-html | 220 ± 10 | 290 ± 20 | 310 ± 20 | 21.1 ± 0.3 |
| GitHub | selectolax | 850 ± 30 | 1,010 ± 40 | 950 ± 30 | 27.7 ± 0.4 |
| GitHub | lxml | 1,000 ± 8 | 1,420 ± 20 | 1,260 ± 10 | 168 ± 1 |
| GitHub | Beautiful Soup | 11,500 ± 80 | 12,600 ± 100 | 13,300 ± 60 | 1,860 ± 20 |
| Wikipedia | astral-html | 1,600 ± 200 | 2,500 ± 200 | 2,200 ± 200 | 362 ± 2 |
| Wikipedia | selectolax | 3,000 ± 300 | 3,900 ± 300 | 3,600 ± 400 | 225 ± 4 |
| Wikipedia | lxml | 4,740 ± 20 | 9,180 ± 40 | 6,230 ± 40 | 1,350 ± 40 |
| Wikipedia | Beautiful Soup | 62,900 ± 500 | 72,500 ± 500 | 90,500 ± 800 | 27,200 ± 200 |

With astral-html’s `tags=["a"]`, parse + links took 18.8 ± 0.2 µs on PyPI,
266 ± 2 µs on GitHub, and 2,120 ± 80 µs on Wikipedia.

## Retained memory

Full and partial parses alternate across seven fresh processes per mode. Each measures
the RSS increase from retaining 64 documents, with garbage collection and `malloc_trim`
before each reading. GitHub used 294 KiB/document (full) and 108 (partial).
Wikipedia used 1,660 and 959. Standard errors rounded to zero at this resolution.

## Fixture sources

[HTML snapshots](fixtures/) are unchanged from [astral-html at b363c5e](https://github.com/astral-sh/astral-html/tree/b363c5e79fb5b896d5ac7b7bd78786fd5e9d196c).
The [PyPI page](https://github.com/astral-sh/astral-tl/blob/04bbd94a054e164a3d057160977197ca25194bc5/benches/tl.rs)
came via [astral-tl](fixtures/LICENSE-astral-tl), the [GitHub and Wikipedia pages](https://github.com/inikulin/parse5/tree/e65eae9a9dc27f1b7eb71868d245ca83070ccc4a/test/data/location-info)
via [parse5](fixtures/LICENSE-parse5). Page content retains its original terms,
including [Wikipedia contributors’ revision 592782173](https://en.wikipedia.org/w/index.php?title=42_(number)&oldid=592782173)
under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/).
