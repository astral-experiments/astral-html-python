# astral-html-python

> [!WARNING]
>
> This project is an experiment in developing a library using Codex. The content below the line, as well as all the code, are written by Codex.

---

A very fast Rust HTML parser with CSS queries for Python, built for scraping.
It uses the [astral-html tokenizer](https://github.com/astral-sh/astral-html)
and builds its own tree in Rust. Python receives element handles on demand.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="benchmarks/filtered-links-dark.png">
    <img src="benchmarks/filtered-links.png" width="660" alt="Mean scrape time for four parsers. astral-html-python took the least time on the Wikipedia, PyPI, and GitHub pages.">
  </picture>
</p>

Each parser reads the same HTML from memory and uses CSS queries to extract link
URLs and text in document order. Each page uses its own time scale. Error bars
show ±1 standard error across 12 fresh processes. [Benchmark details](https://github.com/astral-experiments/astral-html-python/blob/main/benchmarks/README.md).

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
