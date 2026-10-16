# Implementation

## Parsing and storage

`astral-html` tokenizes the input into a source-order tree held in Rust. Nodes
and attributes are stored in arrays; nodes use indices for their parent,
siblings, and the end of their subtree. A full parse keeps a Rust copy of the
input, which the tree can borrow from. Values that need decoding may be owned
by the tree instead.

The parser builds a lexical tree rather than a browser HTML5 DOM. It does not
insert implied elements or repair malformed markup using browser tree-building
rules. An end tag closes the innermost open element of the same name and its
descendants; void elements close immediately. End tags usually match the top of
the stack. If an end tag instead requires searching a deep stack, the parser
builds an index of open tag names and maintains it for the rest of the parse.
SVG and MathML namespaces and browser fragment insertion modes are not tracked.
See the
[upstream safety notes](https://github.com/astral-sh/astral-html/blob/b363c5e79fb5b896d5ac7b7bd78786fd5e9d196c/docs/safety.md)
before using parsed HTML in security-sensitive contexts.

Documents and elements share ownership of the Rust tree. A returned element
holds an index into that tree; its Python properties and query results are
created when requested. Parsing, element scans, and selector matching release
the Python GIL while working with the tree.

## Partial parsing

With `tags`, parsing still tokenizes the full input and tracks open elements,
but retains only matching elements and their subtrees. Retained strings are
copied so the full input can be dropped. This reduces retained memory for some
inputs, but copying and filtering can make it slower than a full parse. See
the [benchmarks](../benchmarks/README.md) for measurements.

The default limits are 128 MiB of UTF-8 input, 4 million retained element/text
nodes, and 256 open non-void elements. The depth limit also applies to branches
discarded by partial parsing.

## Selection

CSS selectors are parsed and matched in Rust against the retained tree. Element
handles are created only for matches. Tag-only enumeration scans the relevant
subtree without parsing a selector. See the [API reference](api.md) for query
behavior and supported selectors. When a caller has little stack space, CSS
selection allocates a temporary larger stack; those calls take longer.

Each query has its own matching budget and caches. The budget counts candidate
checks, tree traversal, attribute lookups, and element identity requests. It
starts at 262,144 units, increasing to 64 units per node in the search range.
Selectors with more than 16 components consume the budget faster. The budget
bounds repeated matching operations. The cost of an individual operation still
depends on the data, such as the length of an attribute value.
Relative-selector caches are discarded in batches, with a separate limit for a
single expensive candidate. Servo's traversal callbacks cannot return errors,
so hitting a limit unwinds directly to the query boundary and becomes a Python
`ValueError`. Results and caches are discarded together.
