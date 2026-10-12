# astral-html-python

A Python library for scraping HTML with [astral-html](https://github.com/astral-sh/astral-html). The parser and tree stay in Rust; Python objects are created as you request them.

We support Python versions in the [bugfix phase](https://devguide.python.org/versions/): currently Python 3.14 and 3.15.

## Quick start

From a checkout, use [uv](https://docs.astral.sh/uv/) to set up the project and build the extension. This requires Rust 1.97 or newer.

```sh
uv sync
uv run python
```

```python
from astral_html import parse

html = '<main><a href="/guide">Read <b>the guide</b></a></main>'
doc = parse(html)
for link in doc.select("main a[href]"):
    print(link.get("href"), link.text)  # /guide Read the guide

first = doc.select_one("a")  # Element | None
if first is not None:
    print(first.tag, first.attrs)  # a {'href': '/guide'}
```

For smaller retained trees, try experimental partial parsing:

```python
links = parse(html, tags=["a"])
for link in links.select("a[href]"):
    print(link.get("href"), link.text)
```

Partial parsing retains matching elements and their subtrees. Discarded
ancestors can change selector results. The parser builds a source-order lexical
tree, which can differ from a browser's HTML5 DOM.

See the [Python API reference](docs/api.md) and [implementation notes](docs/implementation.md) for details.

## Benchmark snapshot

Time to parse a captured page and extract each link's `href` and text, in microseconds per operation. Values are the mean and standard error (SE) over 20 fresh process samples:

| Parser and mode | PyPI | GitHub | Wikipedia |
| --- | ---: | ---: | ---: |
| astral-html, full tree | 14.5 (SE 0.1) | 290 (SE 20) | 2,500 (SE 200) |
| selectolax (Lexbor) | 170 (SE 10) | 1,010 (SE 40) | 3,900 (SE 300) |
| lxml | 163 (SE 0.5) | 1,420 (SE 20) | 9,180 (SE 40) |
| Beautiful Soup (lxml) | 930 (SE 70) | 12,600 (SE 100) | 72,500 (SE 500) |
| astral-html, `tags=["a"]` | 18.8 (SE 0.2) | 266 (SE 2) | 2,120 (SE 80) |

The runner checks that the parsers return the same links before timing. See the [full results and methodology](benchmarks/README.md) for other queries and retained-memory measurements.

## Development

From a checkout:

```sh
uv sync --group benchmark
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run --group benchmark python benchmarks/run.py
```

Licensed under MIT or Apache-2.0.
