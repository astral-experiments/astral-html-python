//! Parse CSS with Servo and match its selectors against the source-order tree.

use std::{borrow::Cow, fmt, ops::Range};

use cssparser::ToCss;
use precomputed_hash::PrecomputedHash;
use selectors::parser::{
    self, Component, ParseRelative, Selector, SelectorList, SelectorParseErrorKind,
};

use crate::tree::Tree;
mod attributes;
mod limits;
mod matching;
use matching::Matcher;

// Matching recurses both across combinators and into selector functions. HTML's
// nesting limit cannot protect shallow trees with long sibling selectors.
const MAX_MATCH_DEPTH: usize = 128;
const MAX_BLOCK_DEPTH: u8 = 32;
pub(crate) const MAX_SELECTOR_BYTES: usize = 256 * 1024;
pub(crate) const SELECTOR_SIZE_ERROR: &str = "CSS selector exceeds the 256 KiB input limit";

/// Work around Servo 0.41 accepting functional :host even with parse_host off.
/// Rename the function so Servo rejects it at the right forgiving-list boundary.
/// This scan also bounds nesting before Servo parses selector functions.
fn prepare_selector(css: &str) -> Result<Cow<'_, str>, String> {
    if !css.contains('(')
        && (css.len() <= usize::from(MAX_BLOCK_DEPTH) || !css.contains(['[', '{']))
    {
        return Ok(Cow::Borrowed(css));
    }
    fn scan(
        input: &mut cssparser::Parser<'_>,
        hosts: &mut Vec<Range<usize>>,
    ) -> Result<(), cssparser::ParseError<()>> {
        loop {
            let start = input.position().byte_index();
            let Ok(token) = input.next_including_whitespace_and_comments() else {
                return Ok(());
            };
            use cssparser::Token::*;
            let host = match token {
                Function(name) => name.eq_ignore_ascii_case("host"),
                ParenthesisBlock | SquareBracketBlock | CurlyBracketBlock => false,
                _ => continue,
            };
            if host {
                hosts.push(start..input.position().byte_index());
            }
            input.parse_nested_block(|input| scan(input, hosts))?;
        }
    }
    let mut input = cssparser::Parser::new(css);
    input.set_nested_block_limit(MAX_BLOCK_DEPTH);
    let mut hosts = Vec::new();
    scan(&mut input, &mut hosts).map_err(|_| {
        format!("CSS selector exceeds the nesting limit ({MAX_BLOCK_DEPTH} blocks)")
    })?;
    if hosts.is_empty() {
        return Ok(Cow::Borrowed(css));
    }
    let mut output = String::new();
    let mut start = 0;
    for host in hosts {
        output.push_str(&css[start..host.start]);
        output.push_str("-astral-unsupported-host(");
        start = host.end;
    }
    output.push_str(&css[start..]);
    Ok(Cow::Owned(output))
}

/// Bound the compounds on any possible matching call path, including nested
/// lists. Alternatives and consecutive simple selectors run sequentially and
/// do not add stack depth. Counting the whole outer chain for each nested list
/// is conservative, including functions in compounds to the left of a sibling.
fn check_match_depth(selector: &Selector<Css>, outer_depth: usize) -> Result<(), String> {
    let depth = outer_depth
        + 1
        + selector
            .iter_raw_match_order()
            .filter(|c| c.is_combinator())
            .count();
    if depth > MAX_MATCH_DEPTH {
        return Err(format!(
            "CSS selector exceeds the matching complexity limit ({MAX_MATCH_DEPTH} nested compounds)"
        ));
    }
    for component in selector.iter_raw_match_order() {
        match component {
            Component::Is(list) | Component::Where(list) | Component::Negation(list) => {
                for nested in list.slice() {
                    check_match_depth(nested, depth)?;
                }
            }
            Component::NthOf(nth) => {
                for nested in nth.selectors() {
                    check_match_depth(nested, depth)?;
                }
            }
            Component::Has(list) => {
                for nested in list.iter() {
                    check_match_depth(&nested.selector, depth)?;
                }
            }
            _ => {}
        }
    }
    Ok(())
}

pub enum SelectError {
    InvalidSelector(String),
    ResourceLimit(String),
}

/// Scan candidates in source order, materializing only matching node indices.
/// `root` scopes the candidates, not the ancestors a selector can inspect.
pub fn select(
    tree: &Tree,
    root: Option<usize>,
    css: &str,
    first: bool,
) -> Result<Vec<usize>, SelectError> {
    // Small Python worker stacks need room for recursive selector matching,
    // including parsing and dropping nested selector lists.
    stacker::maybe_grow(1024 * 1024, 2 * 1024 * 1024, || {
        select_with_stack(tree, root, css, first)
    })
}

// Keep the matcher's frame inside the guarded closure even under optimization.
#[inline(never)]
fn select_with_stack(
    tree: &Tree,
    root: Option<usize>,
    css: &str,
    first: bool,
) -> Result<Vec<usize>, SelectError> {
    if css.len() > MAX_SELECTOR_BYTES {
        return Err(SelectError::ResourceLimit(SELECTOR_SIZE_ERROR.to_owned()));
    }
    let prepared = prepare_selector(css).map_err(SelectError::ResourceLimit)?;
    let mut parser = cssparser::Parser::new(&prepared);
    let selectors = SelectorList::parse(&Css, &mut parser, ParseRelative::No).map_err(|error| {
        SelectError::InvalidSelector(format!("invalid CSS selector {css:?}: {error:?}"))
    })?;
    for selector in selectors.slice() {
        check_match_depth(selector, 0).map_err(SelectError::ResourceLimit)?;
    }
    Matcher::new(tree, root)
        .select(selectors.slice(), first)
        .map_err(|reason| SelectError::ResourceLimit(reason.to_owned()))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct Css;
impl<'i> parser::Parser<'i> for Css {
    type Impl = Css;
    type Error = SelectorParseErrorKind;
    fn parse_is_and_where(&self) -> bool {
        true
    }
    fn parse_has(&self) -> bool {
        true
    }
    fn parse_nth_child_of(&self) -> bool {
        true
    }
}

impl parser::SelectorImpl for Css {
    type AttrValue = CssString;
    type Identifier = CssName;
    type LocalName = CssName;
    type NamespacePrefix = CssName;
    type NamespaceUrl = CssName;
    type BorrowedNamespaceUrl = CssName;
    type BorrowedLocalName = CssName;
    type NonTSPseudoClass = UnsupportedPseudo;
    type PseudoElement = UnsupportedPseudo;
    type ExtraMatchingData<'a> = ();
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct CssName {
    value: String,
}
impl From<&str> for CssName {
    fn from(value: &str) -> Self {
        Self {
            value: value.to_owned(),
        }
    }
}
impl ToCss for CssName {
    fn to_css<W: fmt::Write>(&self, dest: &mut W) -> fmt::Result {
        cssparser::serialize_identifier(&self.value, dest)
    }
}
impl PrecomputedHash for CssName {
    fn precomputed_hash(&self) -> u32 {
        self.value.bytes().fold(2_166_136_261, |hash, byte| {
            (hash ^ u32::from(byte)).wrapping_mul(16_777_619)
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct CssString(String);
impl From<&str> for CssString {
    fn from(value: &str) -> Self {
        Self(value.to_owned())
    }
}
impl AsRef<str> for CssString {
    fn as_ref(&self) -> &str {
        &self.0
    }
}
impl ToCss for CssString {
    fn to_css<W: fmt::Write>(&self, dest: &mut W) -> fmt::Result {
        cssparser::serialize_string(&self.0, dest)
    }
}

// Unsupported pseudo-elements and browser-state pseudo-classes are parse errors.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum UnsupportedPseudo {}
impl parser::PseudoElement for UnsupportedPseudo {}
impl parser::NonTSPseudoClass for UnsupportedPseudo {
    fn is_active_or_hover(&self) -> bool {
        false
    }
    fn is_user_action_state(&self) -> bool {
        false
    }
}
impl ToCss for UnsupportedPseudo {
    fn to_css<W: fmt::Write>(&self, _dest: &mut W) -> fmt::Result {
        match *self {}
    }
}
