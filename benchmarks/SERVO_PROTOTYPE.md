# Servo-backed Python parser prototype

This branch changes `parse(html)` to use Servo's `html5ever` 0.39.0 HTML5
tree builder. `parse(html, parser="lexical")` runs the original, unchanged
astral-html 0.0.3 token-based tree builder in the same extension build. Both
paths use the existing compact tree, Python API, and Servo CSS selector engine.
For this scraper, scripting is disabled: `<noscript>` markup becomes queryable,
as it does in a browser without JavaScript. The HTML5 tree adds implied
`html`/`head`/`body` and `tbody`, closes nested paragraphs, and reparents text
around tables. The targeted tests cover these cases and formatting adoption.

## Captured pages and correctness

The Rust corpus manifest (`corpus/manifest.json` in the resilient Rust
checkout) describes 41 public HTML pages totaling **8,542,490 original bytes**, captured
on October 19, 2026. It records each source URL, retrieval time, SHA-256,
size, and provenance; its separate fetch script reconstructs the ignored
`.corpus/pages/` directory and detects live-page content drift. The 41 pages
include 24 contemporary sites, nine fixed parse5 test fixtures, and eight
small Web Platform Tests HTML fixtures. Original bytes are decoded as UTF-8
with replacement; this particular capture needed zero replacements.

Servo parsed **41/41** pages; the lexical baseline parsed **40/41** at the
default 256 open-element depth limit. The excluded `parse5-huge-page` is
907,953 bytes. On the 40 shared successes, ordered `(href, text)` pairs for
**9,425 `a[href]` elements** matched exactly in both modes. Independently,
Servo's links matched selectolax's Lexbor HTML5 parser on **41/41** pages;
the lexical links matched Lexbor on its 40 successes. This probes only link
extraction, not complete DOM equivalence or all CSS selectors.

The first Servo attempt kept `html5ever`'s scripting-enabled default.
On `astral-home`, it exposed raw `<noscript><img ...></noscript>` markup as
anchor text; on `node-download`, it omitted the link to the downloads archive
inside `<noscript>`. Setting `scripting_enabled=false` makes both outputs
match the lexical parser and Lexbor; a targeted test guards that behavior.

## Python timings

Python 3.14.8, Linux x86-64, AMD EPYC-Milan Processor (16 logical CPUs).
`uv sync` builds the extension with maturin. Each page is read before timing;
five samples per parser and workload are taken in shuffled order. Each sample
times enough repeated operations to run for at least 12 ms, with cyclic GC
enabled. The numbers below sum the five-sample **median** for each page;
the 40 comparable pages contain 7,634,537 bytes. Times include allocation
and conversion of the resulting compact tree. `parse + links` also includes
CSS selection and building all `(href, text)` Python tuples.

| Corpus, 40 shared successes | Lexical | Servo | Servo / lexical |
| --- | ---: | ---: | ---: |
| Parse, sum of page medians | 17.559 ms | 130.075 ms | **7.41×** |
| Parse + extract `a[href]` links | 20.920 ms | 134.395 ms | **6.42×** |

The three committed fixtures (273,705 bytes, all links equal) show the same
cost pattern:

| Fixture | Lexical parse | Servo parse | Lexical parse + links | Servo parse + links |
| --- | ---: | ---: | ---: | ---: |
| PyPI iniconfig, 6,144 B | 8.1 µs | 72.7 µs | 13.9 µs | 80.1 µs |
| parse5 GitHub, 45,233 B | 182.0 µs | 1,380.8 µs | 207.9 µs | 1,474.1 µs |
| parse5 Wikipedia, 222,328 B | 908.6 µs | 6,666.1 µs | 1,358.3 µs | 7,108.4 µs |

## Reproduce

From this Python package checkout with CPython 3.14 and a writable Cargo
cache, install dependencies and rebuild the extension:

```sh
CARGO_HOME=/path/to/writable/cargo-cache uv sync --frozen --group benchmark
uv run --no-sync python benchmarks/servo_comparison.py --samples 5 --min-sample-ms 12
```

For the 41-page corpus, use the separate Rust checkout's `corpus/fetch.py`
and its pinned manifest; bulk HTML stays out of Git. If live pages have
changed, an exact replay requires the original ignored `.corpus/pages` capture.

```sh
python3 /path/to/astral-html-resilient/corpus/fetch.py download
python3 /path/to/astral-html-resilient/corpus/fetch.py verify
uv run --no-sync python benchmarks/servo_comparison.py \
  --corpus /path/to/astral-html-resilient --samples 5 --min-sample-ms 12 \
  --reference-lexbor --output /tmp/python-servo-results.json
```

The benchmark validates file hashes against the manifest and records parse
failures separately; it does not silently drop the rejected page. Run
`pytest`, `ruff check .`, `ruff format --check .`, `ty check`, and
`cargo clippy --locked --all-targets -- -D warnings` for implementation checks.

## Limits and next step

The prototype first builds the complete HTML5 DOM in
`markup5ever_rcdom` 0.39.0+unofficial, then copies it into the original
compact tree. `RcDom` is explicitly unsupported outside upstream's tests,
and the 4-million-node and 256-level limits are only checked during the
copy, after the intermediate DOM has allocated memory. The input-byte limit
is checked before parsing. The peak memory cost was not benchmarked; this
design necessarily holds both DOMs at once during conversion. Template
contents, comments, and doctypes are absent from the queryable compact tree.
Inputs are decoded strings and have no charset detection. The 7× parse-time
regression and unbounded intermediate DOM make this an **experimental
comparison**, not a production-ready replacement. A custom bounded HTML5
`TreeSink` producing the compact tree directly is the clearest next design
experiment; it must support HTML5 node reparenting and be benchmarked again.
