"""A Rust-backed, source-order HTML parser for scraping."""

from ._astral_html import Document, Element, parse

__all__ = ["Document", "Element", "parse"]
