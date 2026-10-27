# astral-html-python

Extract text, attributes, and links from HTML using CSS selectors. The tree
stays in Rust, and Python receives element handles on demand. A handle keeps
its tree alive even after you drop the document. The parser uses
[Astral’s HTML tokenizer](https://github.com/astral-sh/astral-html).

## Quick start

From a checkout with Rust 1.97 or newer, install the package for CPython 3.14
or 3.15. For example, to start a Python 3.14 session, run

```sh
uv sync --locked --python 3.14
uv run python
```

`parse` takes a decoded Python string. If you have response bytes, decode them
using the page’s encoding first. This example uses UTF-8.

```python
from astral_html import parse

body = b'<main><a href="/guide">Read <b>the guide</b></a><a>Draft</a></main>'
doc = parse(body.decode("utf-8"))
links = [(a.get("href"), a.text) for a in doc.select("main a[href]")]
assert links == [("/guide", "Read the guide")]
```

## API

| On a document or element | Result |
| --- | --- |
| `select(css)` | List of matching elements in source order. |
| `select_one(css)` | First matching element, or `None`. |
| `elements(tag=None)` | List of elements in source order, optionally filtered by tag. |

On an element, all three methods search descendants and exclude the element
itself. A CSS selector can still match against ancestors outside that element.
Use `element.select(":scope > a[href]")` for its direct link children.

- `tag`, `parent`, and `children` expose the tag name, parent element (or
  `None`), and direct child elements. Handles compare and hash by node identity.
- `get(name, default=None)` reads one attribute. `attrs` returns a fresh
  dictionary. Names are ASCII-lowercased and the first duplicate attribute wins.
- `text` joins descendant text in source order without inserting spaces. The
  tokenizer normalizes newlines and decodes character references except in raw
  text such as `script`.

### Parsing and selector behavior

The tree follows the nesting in the source. For example, `<p>one<p>two`
produces a paragraph inside a paragraph. Browser HTML5 tree construction can
close the first paragraph or insert implied elements. See the
[upstream parser notes](https://github.com/astral-sh/astral-html/blob/b363c5e79fb5b896d5ac7b7bd78786fd5e9d196c/docs/safety.md).

Supported selectors include `:scope`, `:nth-child`, `:is`, `:not`, and
`:has`. An unsupported selector such as `:hover` raises `ValueError` on its
own. The forgiving lists in `:is()` and `:where()` discard unsupported
alternatives, so `:is(a, :hover)` still matches `a` elements.

### Retaining selected subtrees

The experimental `tags` argument accepts an iterable of tag names, such as
`["a"]`. The parser scans the whole input and retains each matching element
and its descendants. Discarding ancestors changes the selectors you can use.
With the same response body as above,

```python
links_only = parse(body.decode("utf-8"), tags=["a"])
assert [a.text for a in links_only.select("a[href]")] == ["Read the guide"]
assert links_only.select("main a") == []
assert len(links_only.select(":root")) == 2
```

Use a collection or iterator of names even for a single tag. An empty
collection retains no elements.

### Limits

- HTML input is limited to 128 MiB of UTF-8, four million retained nodes, and
  256 simultaneously open non-void elements.
- CSS input is limited to 256 KiB of UTF-8, 32 nested blocks, and 128
  compounds along a matching path. A query that exceeds a work or cache limit
  raises `ValueError` and discards its partial results.

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

CI builds a wheel from the source distribution and tests the installed package
on both supported Python versions. See the
[CI workflow](https://github.com/konsti-openai/astral-html-python/blob/main/.github/workflows/ci.yml).
The package version comes from `Cargo.toml`.

Licensed under MIT or Apache-2.0.
