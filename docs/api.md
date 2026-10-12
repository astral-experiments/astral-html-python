# Python API

```python
from astral_html import Document, Element, parse
```

`parse` creates a `Document`; its query methods return `Element` objects. The
tree stays in Rust, and Python values are created when requested. `Document` and
`Element` cannot be constructed or subclassed directly.

Parsing and the Rust tree scans in `elements`, `select`, and `select_one`
release the Python GIL, including selector parsing and matching. Python result
objects are created after reacquiring it. The immutable tree can be queried
concurrently from multiple threads.

```python
from astral_html import parse

doc = parse('<main><a href="/guide">Read <b>the guide</b></a></main>')
link = doc.select_one("main a[href]")
assert link is not None
assert link.get("href") == "/guide"
assert link.text == "Read the guide"
assert [child.tag for child in link.children] == ["b"]
```

## `parse`

```python
parse(html: str, *, tags: Iterable[str] | None = None) -> Document
```

Parse decoded HTML. Bytes must be decoded before calling `parse`. With the
default `tags=None`, the document retains the complete parsed tree. An empty
input produces an empty document.

`tags` enables experimental partial parsing. It accepts an iterable of tag
names, matched without ASCII case sensitivity. Each matching element and its
entire subtree are retained; unrelated branches and ancestors are discarded.
Nested matches appear only once, and `tags=[]` retains no elements. The input is
still read in full.

```python
doc = parse('<main><a href="/guide">Read <b>more</b></a></main>', tags=["a"])
assert [element.tag for element in doc.elements()] == ["a", "b"]
assert doc.select_one("a > b") is not None
assert doc.select_one("main a") is None  # main was discarded
```

Retained elements whose ancestors were discarded become roots. Queries that
depend on ancestors, siblings, or positions can therefore differ from a full
parse. The filter is not a CSS selector.

Passing a string as `tags`, a non-string tag name, or non-string HTML raises
`TypeError`. An empty tag name raises `ValueError`. Parsing also raises
`ValueError` if the input exceeds 128 MiB in UTF-8, the tree exceeds 4,000,000
retained element and text nodes, or nesting exceeds 256 open non-void elements.
The byte and nesting limits apply even to discarded branches.

## `Document`

- `elements(tag: str | None = None) -> list[Element]`: return all retained
  elements, optionally filtered by tag name without ASCII case sensitivity.
- `select(css: str) -> list[Element]`: return all elements matching a CSS
  selector.
- `select_one(css: str) -> Element | None`: return the first match, or `None`.

Results are in source order. A selector list does not return the same element
more than once. See [CSS selectors](#css-selectors) for scope and errors.

## `Element`

Properties:

- `tag: str` is the ASCII-lowercased tag name.
- `attrs: dict[str, str]` is a new dictionary of attributes. Attribute names
  are ASCII-lowercased and the first occurrence of a duplicate is kept. A
  valueless attribute has an empty string as its value. Changing the dictionary
  does not change the tree.
- `text: str` concatenates all descendant text in source order without
  collapsing whitespace or adding separators; comments are excluded. CRLF
  and CR are normalized to LF in text and attribute values. Character
  references are decoded in ordinary text and attributes, while raw-text
  elements such as `script` and `style` retain their raw text.
- `parent: Element | None` is the retained parent, if any.
- `children: list[Element]` contains immediate element children, excluding
  text and comments.

Methods:

- `get(name: str) -> str | None` and `get(name: str, default: T) -> str | T`
  read one attribute without building the `attrs` dictionary. Attribute names
  are matched without ASCII case sensitivity. A missing attribute returns
  `default`, or `None` if it is omitted.
- `elements(tag: str | None = None) -> list[Element]` returns descendants,
  optionally filtered by tag name.
- `select(css: str) -> list[Element]` returns matching descendants.
- `select_one(css: str) -> Element | None` returns the first matching
  descendant, or `None`.

Element queries exclude the element itself. Lists are in source order. Each
`Element` keeps the underlying tree alive even if its `Document` is deleted.
Properties and query results are read-only views or newly created Python values;
the API does not mutate the tree.

Elements compare equal and have equal hashes when they refer to the same node
in the same parsed document, even when obtained through different queries or
traversal properties. They can be used as dictionary keys or set members.
Different nodes, and nodes from separately parsed documents (even identical
HTML), compare unequal. Equality does not compare markup or text, and ordering
comparisons are unsupported.

## CSS selectors

Selectors support tags, IDs, classes, attributes, selector lists, descendant,
child and sibling combinators, and structural pseudo-classes including
`:first-child`, `:nth-child`, `:not`, `:is`, `:where`, and `:has`. Invalid or
unsupported selectors raise `ValueError`. Browser-state pseudo-classes such as
`:hover` and pseudo-elements are unsupported. As in CSS, `:is()` and `:where()`
can discard invalid alternatives.

To bound matching depth, selectors may use at most 32 nested CSS blocks and
128 compounds along a path through nested selector functions. Selectors that
exceed these limits raise `ValueError`.

For an `Element` query, `:scope` refers to that element, so use
`element.select(":scope > a")` for its direct link children. The selector may
inspect ancestors outside the element, but the results contain only its
descendants. A selector cannot start with a combinator such as `> a`; use
`:scope > a` instead. In a document query, `:scope` and `:root` match retained
elements without a parent, which can be multiple elements in a fragment or a
partial parse.

The parser builds a source-order lexical tree, not a browser HTML5 DOM: it does
not insert implied elements or apply browser error recovery. Selectors operate
on this tree, so malformed markup may produce different results from a browser.
