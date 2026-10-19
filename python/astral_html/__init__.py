"""A Rust-backed HTML5 parser and selector engine for scraping."""

from ._astral_html import Document, Element, parse

__all__ = ["Document", "Element", "parse"]
