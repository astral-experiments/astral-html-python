# astral-html-python

> [!WARNING]
>
> This project is an experiment in developing a library using Codex. The content below the line, as well as all the code, are written by Codex.

---

A very fast HTML parser with CSS selectors for Python web scrapers. It’s written
in Rust and uses the [astral-html](https://github.com/astral-sh/astral-html) tokenizer.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="benchmarks/filtered-links-dark.png">
    <img src="benchmarks/filtered-links.png" width="660" alt="Mean scrape time for four parsers. astral-html-python took the least time on the Wikipedia, PyPI, and GitHub pages.">
  </picture>
</p>

Time to parse a saved page and extract link URLs and text with CSS (mean ±1
standard error). Each page has its own scale. [Benchmark details](https://github.com/astral-experiments/astral-html-python/blob/main/benchmarks/README.md#time-per-operation).

## Quick start

With `uv` and Rust 1.97+ installed, start CPython 3.14 or 3.15 from the
repository root.

```sh
uv run --locked --python 3.14 python
```

Pass the page HTML as a string, then select the links that have an `href`.

```python
from astral_html import parse

doc = parse('<main><a href="/guide">Read <b>the guide</b></a><a>Draft</a></main>')
links = [(a.get("href"), a.text) for a in doc.select("main a[href]")]
print(links)  # [('/guide', 'Read the guide')]
```

[Parsing and CSS queries](https://github.com/astral-experiments/astral-html-python/blob/main/docs/parsing.md) ·
[Development guide](https://github.com/astral-experiments/astral-html-python/blob/main/docs/development.md)

Licensed under MIT or Apache-2.0.
