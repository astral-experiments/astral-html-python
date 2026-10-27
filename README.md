This project is an experiment in developing a library using Codex. The content below the line, as well as all the code, are written by Codex.

---

# astral-html-python

A very fast Rust HTML parser with CSS queries for Python, built for scraping.
It uses the [astral-html tokenizer](https://github.com/astral-sh/astral-html)
and builds its own tree in Rust. Python receives element handles on demand.

[![Time to extract links from PyPI, GitHub, and Wikipedia pages. astral-html-python had the lowest mean time on all three.](benchmarks/filtered-links.png)](https://github.com/astral-experiments/astral-html-python/blob/main/benchmarks/filtered-links.png)

This benchmark extracts the same ordered `(href, descendant text)` pairs from
UTF-8 bytes for a PyPI package index, a GitHub file listing, and a Wikipedia
article. On the GitHub page, for example, parsing and extracting seven file or
directory links took 268 µs with this library and 391 µs with selectolax (Lexbor).
The plot shows the mean time per scrape, with error bars of one standard error
across 12 fresh worker processes. Disk and network I/O are outside the timer.
[Benchmark details](https://github.com/astral-experiments/astral-html-python/blob/main/benchmarks/README.md)
and [plot data](https://github.com/astral-experiments/astral-html-python/blob/main/benchmarks/filtered-links.json).

## Quick start

From a checkout, install Rust 1.97 or newer and use `uv` with CPython 3.14 or
3.15. For example, start a Python 3.14 session with

```sh
uv sync --locked --python 3.14
uv run python
```

Parse a page and extract links with a CSS query. Decode response bytes using the
page's encoding before parsing. This example uses UTF-8.

```python
from astral_html import parse

body = b'<main><a href="/guide">Read <b>the guide</b></a><a>Draft</a></main>'
doc = parse(body.decode("utf-8"))
links = [(a.get("href"), a.text) for a in doc.select("main a[href]")]
assert links == [("/guide", "Read the guide")]
```

See [parsing and CSS queries](https://github.com/astral-experiments/astral-html-python/blob/main/docs/parsing.md)
for the API, tree behavior, and limits. See the [development guide](https://github.com/astral-experiments/astral-html-python/blob/main/docs/development.md)
for tests and contributor setup.

Licensed under MIT or Apache-2.0.
