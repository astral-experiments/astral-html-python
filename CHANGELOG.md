# Changelog

## 0.0.2

- Remove `stacker` and nine transitive Rust dependencies from source builds.
  CSS queries now use the calling thread's stack. Deeply nested selectors can
  crash Python on unusually small worker stacks (e.g. 64 KiB).
- Pin the benchmark charts on PyPI to the release commit.

## 0.0.1

- Parse HTML from Python and query elements with CSS selectors.
- Read element attributes, extract descendant text, and iterate over mixed text and child elements in source order.
