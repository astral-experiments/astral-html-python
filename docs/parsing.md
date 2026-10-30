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
- `link["href"]` reads a required attribute and raises `KeyError` if it is
  missing. Use `link.get("href", default)` for an optional attribute. The
  default is `None` when omitted. Both lookups ignore ASCII case. A relative
  URL stays relative. Test presence with `"disabled" in element`. This also
  finds boolean attributes whose value is an empty string.
- `link.attrs` is a read-only mapping with ASCII-lowercased keys. For example,
  `link["HREF"]` and `link.attrs["href"]` read the same attribute. Use
  `dict(link.attrs)` for a mutable copy. Tag names are also ASCII-lowercased,
  and the first duplicate attribute wins.
- `text` joins descendant text in source order without inserting spaces.
  The tokenizer normalizes newlines and decodes character references except
  in raw text such as `script`.
- `iter_text()` yields those same text fragments one at a time, preserving
  whitespace. Joining them with `""` gives `.text`. For
  `<p>New<br>York</p>`, the fragments are `"New"` and `"York"`. For
  `<p>NewYork<br></p>`, the only fragment is `"NewYork"`. Tags such as
  `br` contribute no text of their own.
- `iter_content()` yields the element’s direct text fragments and child elements
  in source order. This example turns a paragraph’s direct `br` children
  into newlines.

```python
(p,) = parse("<p><br>A<i>B</i><br></p>").select("p")
parts = []
for child in p.iter_content():
    if isinstance(child, str):
        parts.append(child)
    elif child.tag == "br":
        parts.append("\n")
    else:
        parts.append(child.text)
assert "".join(parts) == "\nAB\n"
```

CSS queries support attribute selectors, combinators, and pseudo-classes such
as `:scope`, `:nth-child()`, `:is()`, `:not()`, and `:has()`. Invalid or
unsupported selectors such as `:hover` raise `astral_html.InvalidSelectorError`
on their own.
Forgiving lists in `:is()` and `:where()` discard unsupported alternatives,
so `:is(a, :hover)` still matches `a` elements.

## Retaining selected subtrees

The experimental `retain_subtrees` keyword accepts one tag name or an iterable
of names. Matching ignores ASCII case. The parser reads the whole input and
retains each matching element and its descendants. Queries use the resulting tree.
For example, links that had different parents in the input can become
adjacent roots and match the sibling selector `a + a`.

```python
from astral_html import parse

source = '<nav><a href="/">Home</a></nav><main><a><b>Draft</b></a></main>'
links = parse(source, retain_subtrees="a")
assert [a.text for a in links.select(":root")] == ["Home", "Draft"]
assert [a.text for a in links.select("a + a")] == ["Draft"]
assert links.select("nav a") == []
assert [b.text for b in links.select("a > b")] == ["Draft"]
```

Pass `retain_subtrees=["a", "img"]` for several tags. An empty iterable
retains no elements. This keyword replaces the experimental `tags` keyword.
The benchmarks compare how much memory full and partial trees retain. [Retained memory](../benchmarks/README.md#retained-memory)

## Resource limits

- HTML input is limited to 128 MiB measured as UTF-8, four million retained
  element and text nodes, and 256 simultaneously open non-void elements. The
  byte and nesting limits also apply when parsing with `retain_subtrees`.
- CSS input is limited to 256 KiB measured as UTF-8, 32 nested blocks, and
  128 compounds along a matching path. Complex queries can also exceed a
  matching work or cache limit.

Exceeding an HTML or CSS limit raises `astral_html.ResourceLimitError`. A query
discards matches it found before reaching the limit. Both `ResourceLimitError`
and `InvalidSelectorError` inherit from `ValueError`.

Servo parses CSS, but its matching callbacks cannot return an error. The
extension walks the parsed selectors itself so it can propagate a limit error
with Rust’s `Result`. Builders can choose `panic = "abort"` or `panic = "unwind"`
and get the same Python exception. On small Python worker stacks, `stacker`
provides room for recursive selector matching.

Applications processing untrusted pages should also bound response size and
concurrent parses. The tokenizer reads a start tag and its attributes even
when the subtree filter later discards it. Peak memory therefore depends on
the largest token as well as the number of retained nodes.

## Threads

Parsing and searches release the GIL during native tree work. On free-threaded
CPython, importing this module enables the GIL by default.
The extension supports ordinary Python threads. It cannot currently load
in a CPython subinterpreter, including workers in `InterpreterPoolExecutor`.
