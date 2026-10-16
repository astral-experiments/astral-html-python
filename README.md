# astral-html-python

Scrape HTML from Python with [astral-html](https://github.com/astral-sh/astral-html).
The tree stays in Rust. Python objects are created as you request them, and an
element remains usable after you drop its document.

From a checkout, run `uv sync --locked` (CPython 3.14 or 3.15, Rust 1.97+).
Then in `uv run python`:

```python
from astral_html import parse

doc = parse('<main><a href="/guide">Read <b>the guide</b></a></main>')
(link,) = doc.select("main a[href]")
link.get("href")  # '/guide'
link.text  # 'Read the guide'
```

## API

`parse(html)` takes a decoded string and builds a tree in source order.
It preserves the nesting you wrote, including a `<p>` inside another `<p>`.
It does not insert implied elements or apply browser HTML5 error recovery.
See the [parser’s safety notes](https://github.com/astral-sh/astral-html/blob/b363c5e79fb5b896d5ac7b7bd78786fd5e9d196c/docs/safety.md).

On a document or element, queries return matches in source order:

- `select(css)` returns a list. On an element it searches descendants,
  excluding the element itself. Use `element.select(":scope > a")` for direct children.
- `select_one(css)` returns the first match, or `None`.
- `elements(tag=None)` lists elements, optionally filtered by tag name.

Elements expose `tag`, `parent`, `children`, a fresh `attrs` dictionary, and
`get(name, default=None)`. Tag and attribute names are ASCII-lowercased. The
first duplicate attribute wins. `text` joins descendant text without adding spaces,
normalizes newlines, and decodes character references except in raw text such as
`script`. Elements compare and hash by node identity.

`parse(html, tags=["a"])` is an experimental way to retain just matching elements
and their subtrees. It still reads the entire input. Discarded ancestors change
query results: a retained link can match `:root` and no longer match `main a`.

CSS includes `:scope`, `:nth-child`, `:is`, `:not`, and `:has`. Unsupported
selectors such as `:hover` raise `ValueError`, as do resource limits:

- HTML: 128 MiB of UTF-8, 4 million retained nodes, 256 open elements.
- CSS: 256 KiB of UTF-8, 32 nested blocks, 128 compounds along a selector path.
  Expensive queries can also hit a work or cache limit. No partial results are returned.

Parsing and queries release the GIL. Importing on free-threaded CPython currently enables it.

## Performance

In a captured Wikipedia page benchmark, parsing and extracting link URLs and text
averaged 1.34 ms (standard error 0.005 ms) over 12 fresh processes. The full tree
used about 651 KiB per document. Retaining only link subtrees used 295 KiB.
See [benchmarks](benchmarks/README.md) for the workloads, comparisons, and commands.

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run ty check
cargo fmt --check && cargo clippy --locked --all-targets -- -D warnings
```

[CI](.github/workflows/ci.yml) builds a wheel from the source distribution and tests
the installed package. Set the package version in `Cargo.toml`. License: MIT or Apache-2.0.
