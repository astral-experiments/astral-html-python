# Scraping benchmarks

```sh
uv run --group benchmark python benchmarks/run.py --samples 12 --min-sample-ms 12
uv run --group benchmark python benchmarks/run.py --memory  # Linux with glibc
```

Every parser must return Lexbor’s exact, ordered `(href, text)` pairs for all links and
for a page-specific query (PyPI downloads with Python requirements, GitHub files, or
Wikipedia article links). Parsers can still differ in how they recover malformed HTML.

## Time per operation, µs (mean ± standard error)

Release build of astral-html 0.1.0 on Python 3.14.8, with selectolax 1.0.0,
lxml 6.1.3, cssselect 1.5.0 and Beautiful Soup 4.15.0 (using lxml).
Each of 12 fresh processes on one CPU shuffles the workloads and times batches of at
least 12 ms. Timing includes building the output, excludes file I/O, and leaves cyclic GC
enabled. “Query on tree” starts with a parsed document and uses each library’s normal
selector caching.

| Page | Parser | Parse | Parse + links | Parse + filtered | Query on tree |
| --- | --- | ---: | ---: | ---: | ---: |
| PyPI | astral-html | 7.79 ± 0.05 | 14.5 ± 0.3 | 12.5 ± 0.1 | 4.11 ± 0.08 |
| PyPI | selectolax | 56.8 ± 3 | 113 ± 6 | 110 ± 7 | 9.0 ± 0.6 |
| PyPI | lxml | 60.6 ± 3 | 191 ± 10 | 168 ± 4 | 91 ± 10 |
| PyPI | Beautiful Soup | 777 ± 40 | 882 ± 5 | 906 ± 10 | 123 ± 3 |
| GitHub | astral-html | 160 ± 2 | 208 ± 2 | 193 ± 3 | 20.9 ± 0.1 |
| GitHub | selectolax | 580 ± 60 | 929 ± 50 | 808 ± 20 | 27.4 ± 0.2 |
| GitHub | lxml | 1,010 ± 9 | 1,410 ± 10 | 1,240 ± 8 | 171 ± 3 |
| GitHub | Beautiful Soup | 11,800 ± 100 | 12,800 ± 100 | 13,500 ± 70 | 1,830 ± 10 |
| Wikipedia | astral-html | 847 ± 4 | 1,340 ± 5 | 1,230 ± 10 | 398 ± 40 |
| Wikipedia | selectolax | 2,200 ± 100 | 3,720 ± 200 | 2,720 ± 100 | 220 ± 0.8 |
| Wikipedia | lxml | 4,690 ± 9 | 8,930 ± 40 | 6,080 ± 20 | 1,320 ± 10 |
| Wikipedia | Beautiful Soup | 65,600 ± 400 | 74,700 ± 300 | 92,100 ± 800 | 26,600 ± 100 |

With astral-html’s `tags=["a"]`, parse + links took 14.7 ± 1 µs on PyPI,
186 ± 6 µs on GitHub, and 1,240 ± 6 µs on Wikipedia.

## Retained memory

Full and partial parses alternate across seven fresh processes per mode. Each measures
the RSS increase from retaining 64 documents, with garbage collection and `malloc_trim`
before each reading. Full and partial trees used 15 and 10 KiB/document on PyPI,
135 and 39 on GitHub, and 651 and 295 on Wikipedia. Standard errors were below
0.1 KiB. Absolute RSS depends on the allocator and process history.

## Fixture sources

[HTML snapshots](fixtures/) are unchanged from [astral-html at b363c5e](https://github.com/astral-sh/astral-html/tree/b363c5e79fb5b896d5ac7b7bd78786fd5e9d196c).
The [PyPI page](https://github.com/astral-sh/astral-tl/blob/04bbd94a054e164a3d057160977197ca25194bc5/benches/tl.rs)
came via [astral-tl](fixtures/LICENSE-astral-tl), the [GitHub and Wikipedia pages](https://github.com/inikulin/parse5/tree/e65eae9a9dc27f1b7eb71868d245ca83070ccc4a/test/data/location-info)
via [parse5](fixtures/LICENSE-parse5). Page content retains its original terms,
including [Wikipedia contributors’ revision 592782173](https://en.wikipedia.org/w/index.php?title=42_(number)&oldid=592782173)
under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/).
