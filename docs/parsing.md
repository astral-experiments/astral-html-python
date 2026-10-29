# Parsing and querying HTML

## Tree construction

`parse(html)` accepts a decoded Python string. If your HTTP client returns
bytes, decode them using the page's encoding before calling `parse`.

Elements follow the nesting in the source. For example, `<p>one<p>two` puts the
second paragraph inside the first. A browser closes the first paragraph when it
encounters the second.

An end tag closes the innermost open element with that name and any open
descendants. Unmatched end tags are ignored. Void elements such as `br` have
no children. Other elements stay open until a matching end tag, an ancestor's
end tag, or the end of the input, even if their start tag ends in `/>`.
The tree can have several roots. Text outside those roots is discarded.
[Upstream parser notes](https://github.com/astral-sh/astral-html/blob/bb211c502d6ceaf4e2843d782afe2b24d5d8a49a/docs/safety.md)

## Queries and element handles

The tree stays in Rust. Queries create Python handles for the elements they
return.

`select(css)` returns matching elements in source order. Use `select("a")`
for anchors or `select("*")` for every element. Escape characters that have a
special meaning in CSS. For example, `select(r"x\:card")` matches a tag named
`x:card`. `select_one(css)` returns the first match, or `None` if there is no
match.

On an element, both methods search its descendants. A selector can still
use ancestors above that element when deciding whether a descendant matches.
Use `:scope` to refer to the element you called the method on.

```python
from astral_html import parse

doc = parse(
    '<article><section><a href="/guide">Read <b>the guide</b></a></section></article>'
)
(section,) = doc.select("section")
(link,) = section.select("article a[href]")
assert section.select(":scope > a") == [link]
assert section.select("section") == []
assert link.text == "Read the guide"
```

- `tag`, `parent`, and `children` give the tag name, parent element (or
  `None`), and direct child elements. Handles to the same node compare equal
  and have the same hash. Each handle keeps its tree alive.
- `get(name, default=None)` reads one attribute and returns the default when
  the attribute is absent. For example, `link.get("href")` above returns
  `"/guide"`. A relative URL stays relative. `attrs` returns a fresh
  dictionary. Tag and attribute names use ASCII lowercase, and the first
  duplicate attribute wins.
- `text` joins descendant text in source order without inserting spaces.
  The tokenizer normalizes newlines and decodes character references except
  in raw text such as `script`.

CSS queries support attribute selectors, combinators, and pseudo-classes such
as `:scope`, `:nth-child()`, `:is()`, `:not()`, and `:has()`. Invalid or
unsupported selectors such as `:hover` raise `ValueError` on their own.
Forgiving lists in `:is()` and `:where()` discard unsupported alternatives,
so `:is(a, :hover)` still matches `a` elements.

## Retaining selected subtrees

The experimental `tags` argument takes an iterable of tag names, matched
without regard to ASCII case. The parser reads the whole input and retains
each matching element and its descendants. Queries use the resulting tree.
For example, links that had different parents in the input can become
adjacent roots and match the sibling selector `a + a`.

```python
from astral_html import parse

source = '<nav><a href="/">Home</a></nav><main><a><b>Draft</b></a></main>'
links = parse(source, tags=["a"])
assert [a.text for a in links.select(":root")] == ["Home", "Draft"]
assert [a.text for a in links.select("a + a")] == ["Draft"]
assert links.select("nav a") == []
assert [b.text for b in links.select("a > b")] == ["Draft"]
```

For one tag, pass `tags=["a"]`. A bare string raises `TypeError`, and an
empty iterable retains no elements. The benchmarks compare how much memory
full and partial trees retain. [Retained memory](../benchmarks/README.md#retained-memory)

## Resource limits

- HTML input is limited to 128 MiB measured as UTF-8, four million retained
  element and text nodes, and 256 simultaneously open non-void elements. The
  byte and nesting limits also apply when parsing with `tags`.
- CSS input is limited to 256 KiB measured as UTF-8, 32 nested blocks, and
  128 compounds along a matching path. Complex queries can also exceed a
  matching work or cache limit.

Exceeding a limit raises `ValueError`. A query discards matches it found
before reaching the limit.

## Threads

Parsing and searches release the GIL during native tree work. On free-threaded
CPython, importing this module enables the GIL by default.
