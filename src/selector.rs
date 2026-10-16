//! CSS selectors over the source-order tree.
//!
//! Parsing and matching are provided by Servo's `selectors` crate. The tree
//! adapter exposes only the HTML context supported by the parser: there are no
//! namespaces, shadow roots, or runtime browser state.

use std::{borrow::Cow, fmt, ops::Range};

use cssparser::ToCss;
use precomputed_hash::PrecomputedHash;
use selectors::attr::{
    AttrSelectorOperation, AttrSelectorOperator, CaseSensitivity, NamespaceConstraint,
};
use selectors::bloom::BloomFilter;
use selectors::matching::{self, ElementSelectorFlags};
use selectors::parser::{
    self, Component, ParseRelative, Selector, SelectorList, SelectorParseErrorKind,
};
use selectors::{Element, OpaqueElement};

use crate::tree::{Kind, Tree};
mod limits;
use limits::MatchBudget;

// Servo recurses both across combinators and into selector functions. HTML's
// nesting limit cannot protect shallow trees with long sibling selectors.
const MAX_MATCH_DEPTH: usize = 128;
const MAX_BLOCK_DEPTH: u8 = 32;
const MAX_SELECTOR_BYTES: usize = 256 * 1024;

/// Work around Servo 0.41 accepting functional :host even with parse_host off.
/// Rename its function token to an unsupported name so Servo itself handles
/// errors at the right forgiving-list boundary. A global rejection would break
/// e.g. :not(:is(:host(div), .x)). Tokenization preserves strings, comments, and
/// escaped identifiers; it also bounds nesting before Servo parses functions.
fn prepare_selector(css: &str) -> Result<Cow<'_, str>, String> {
    if !css.contains('(') {
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
            let host = matches!(token, cssparser::Token::Function(name) if name.eq_ignore_ascii_case("host"));
            let block = matches!(
                token,
                cssparser::Token::Function(_)
                    | cssparser::Token::ParenthesisBlock
                    | cssparser::Token::SquareBracketBlock
                    | cssparser::Token::CurlyBracketBlock
            );
            if host {
                hosts.push(start..input.position().byte_index());
            }
            if block {
                input.parse_nested_block(|input| scan(input, hosts))?;
            }
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
fn check_match_depth(
    selector: &Selector<Css>,
    outer_depth: usize,
    shape: &mut SelectorShape,
) -> Result<(), String> {
    let mut depth = outer_depth + 1;
    for component in selector.iter_raw_match_order() {
        shape.components += 1;
        depth += usize::from(matches!(component, Component::Combinator(_)));
    }
    if depth > MAX_MATCH_DEPTH {
        return Err(format!(
            "CSS selector exceeds the matching complexity limit ({MAX_MATCH_DEPTH} nested compounds)"
        ));
    }
    for component in selector.iter_raw_match_order() {
        match component {
            Component::Is(list) | Component::Where(list) | Component::Negation(list) => {
                for nested in list.slice() {
                    check_match_depth(nested, depth, shape)?;
                }
            }
            Component::NthOf(nth) => {
                for nested in nth.selectors() {
                    check_match_depth(nested, depth, shape)?;
                }
            }
            Component::Has(list) => {
                shape.has_relative = true;
                for nested in list.iter() {
                    check_match_depth(&nested.selector, depth, shape)?;
                }
            }
            _ => {}
        }
    }
    Ok(())
}

#[derive(Default)]
struct SelectorShape {
    has_relative: bool,
    components: usize,
}

/// Scan candidates in source order, materializing only matching node indices.
/// `root` scopes the candidates, not the ancestors a selector can inspect.
pub fn select(
    tree: &Tree<'_>,
    root: Option<usize>,
    css: &str,
    first: bool,
) -> Result<Vec<usize>, String> {
    // Python can call us on a worker with a very small native stack. Alongside
    // bounded selector recursion, :has() recursively walks up to 256 HTML
    // levels. Reserve headroom for both before parsing, matching, or dropping
    // nested selectors. Normal callers with enough stack do not allocate.
    stacker::maybe_grow(1024 * 1024, 2 * 1024 * 1024, || {
        select_with_stack(tree, root, css, first)
    })
}

// Keep the matcher's frame inside the guarded closure even under optimization.
#[inline(never)]
fn select_with_stack(
    tree: &Tree<'_>,
    root: Option<usize>,
    css: &str,
    first: bool,
) -> Result<Vec<usize>, String> {
    if css.len() > MAX_SELECTOR_BYTES {
        return Err("CSS selector exceeds the 256 KiB input limit".to_owned());
    }
    let prepared = prepare_selector(css)?;
    let mut parser = cssparser::Parser::new(&prepared);
    let selectors = SelectorList::parse(&CssParser, &mut parser, ParseRelative::No)
        .map_err(|error| format!("invalid CSS selector {css:?}: {error:?}"))?;
    let selectors = selectors.slice();
    let mut shape = SelectorShape::default();
    for selector in selectors {
        check_match_depth(selector, 0, &mut shape)?;
    }
    // Only a literal tag in the rightmost compound is required of every match.
    // Selector lists and selectors without a literal tag use the full matcher for each node.
    let tag = match selectors {
        [selector] => selector.iter().find_map(|component| match component {
            Component::LocalName(name) => Some(name.lower_name.value.as_str()),
            _ => None,
        }),
        _ => None,
    };
    let (start, end) = root.map_or((0, tree.nodes.len()), |i| (i + 1, tree.nodes[i].end));
    let budget = MatchBudget::new(end - start, shape);
    let mut caches = matching::SelectorCaches::default();
    let mut context = matching::MatchingContext::new(
        matching::MatchingMode::Normal,
        None,
        &mut caches,
        matching::QuirksMode::NoQuirks,
        matching::NeedsSelectorFlags::No,
        matching::MatchingForInvalidation::No,
    );
    context.scope_element = root.map(|i| OpaqueElement::new(&tree.nodes[i]));
    limits::with_match_limits(move || {
        let mut output = Vec::new();
        for index in start..end {
            let Kind::Element { name, .. } = &tree.nodes[index].kind else {
                continue;
            };
            if tag.is_some_and(|tag| tag != name.as_ref()) {
                continue;
            }
            budget.start_element(context.selector_caches);
            let element = ElementRef {
                tree,
                index,
                budget: &budget,
            };
            if selectors.iter().any(|selector| {
                budget.visit();
                matching::matches_selector(selector, 0, None, &element, &mut context)
            }) {
                output.push(index);
                if first {
                    break;
                }
            }
        }
        output
    })
}

#[derive(Clone, Copy, Debug)]
struct CssParser;
impl<'i> parser::Parser<'i> for CssParser {
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct Css;
impl parser::SelectorImpl for Css {
    type AttrValue = CssString;
    type Identifier = CssName;
    type LocalName = CssName;
    type NamespacePrefix = CssName;
    type NamespaceUrl = CssName;
    type BorrowedNamespaceUrl = CssName;
    type BorrowedLocalName = CssName;
    type NonTSPseudoClass = NonTSPseudoClass;
    type PseudoElement = PseudoElement;
    type ExtraMatchingData<'a> = ();
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct CssName {
    value: String,
    hash: u32,
}
impl From<&str> for CssName {
    fn from(value: &str) -> Self {
        let hash = value.bytes().fold(2_166_136_261, |hash, byte| {
            (hash ^ u32::from(byte)).wrapping_mul(16_777_619)
        });
        Self {
            value: value.to_owned(),
            hash,
        }
    }
}
impl Default for CssName {
    fn default() -> Self {
        Self::from("")
    }
}
impl ToCss for CssName {
    fn to_css<W: fmt::Write>(&self, dest: &mut W) -> fmt::Result {
        cssparser::serialize_identifier(&self.value, dest)
    }
}
impl PrecomputedHash for CssName {
    fn precomputed_hash(&self) -> u32 {
        self.hash
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

// Static markup has no browser state. Unsupported pseudo-classes and
// pseudo-elements are parse errors rather than silent non-matches.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum NonTSPseudoClass {}
impl parser::NonTSPseudoClass for NonTSPseudoClass {
    fn is_active_or_hover(&self) -> bool {
        false
    }
    fn is_user_action_state(&self) -> bool {
        false
    }
}
impl ToCss for NonTSPseudoClass {
    fn to_css<W: fmt::Write>(&self, _dest: &mut W) -> fmt::Result {
        match *self {}
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum PseudoElement {}
impl parser::PseudoElement for PseudoElement {}
impl ToCss for PseudoElement {
    fn to_css<W: fmt::Write>(&self, _dest: &mut W) -> fmt::Result {
        match *self {}
    }
}

#[derive(Clone, Copy)]
struct ElementRef<'tree, 'source> {
    tree: &'tree Tree<'source>,
    index: usize,
    budget: &'tree MatchBudget,
}
impl fmt::Debug for ElementRef<'_, '_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_tuple("ElementRef").field(&self.index).finish()
    }
}
impl<'tree, 'source> ElementRef<'tree, 'source> {
    fn name(&self) -> &str {
        match &self.tree.nodes[self.index].kind {
            Kind::Element { name, .. } => name,
            Kind::Text(_) => unreachable!("selector references must be elements"),
        }
    }
    fn attribute(&self, name: &str) -> Option<&str> {
        self.budget.visit();
        match &self.tree.nodes[self.index].kind {
            Kind::Element { attrs, .. } => self.tree.attributes[attrs.clone()]
                .iter()
                .find(|attribute| attribute.name == name)
                .map(|attribute| attribute.value()),
            Kind::Text(_) => unreachable!("selector references must be elements"),
        }
    }
    fn at(&self, index: usize) -> Self {
        self.budget.visit();
        Self { index, ..*self }
    }
}

impl Element for ElementRef<'_, '_> {
    type Impl = Css;
    fn opaque(&self) -> OpaqueElement {
        self.budget.record_identity();
        OpaqueElement::new(&self.tree.nodes[self.index])
    }
    fn parent_element(&self) -> Option<Self> {
        self.tree.nodes[self.index]
            .parent
            .map(|index| self.at(index))
    }
    fn parent_node_is_shadow_root(&self) -> bool {
        false
    }
    fn containing_shadow_host(&self) -> Option<Self> {
        None
    }
    fn is_pseudo_element(&self) -> bool {
        false
    }
    fn prev_sibling_element(&self) -> Option<Self> {
        self.tree.nodes[self.index]
            .prev_sibling
            .map(|index| self.at(index))
    }
    fn next_sibling_element(&self) -> Option<Self> {
        self.tree.nodes[self.index]
            .next_sibling
            .map(|index| self.at(index))
    }
    fn first_element_child(&self) -> Option<Self> {
        let mut index = self.index + 1;
        let end = self.tree.nodes[self.index].end;
        while index < end {
            let node = &self.tree.nodes[index];
            if matches!(node.kind, Kind::Element { .. }) {
                return Some(self.at(index));
            }
            self.budget.visit();
            index = node.end;
        }
        None
    }
    fn is_html_element_in_html_document(&self) -> bool {
        true
    }
    fn has_local_name(&self, name: &CssName) -> bool {
        self.name() == name.value
    }
    fn has_namespace(&self, namespace: &CssName) -> bool {
        namespace.value.is_empty()
    }
    fn is_same_type(&self, other: &Self) -> bool {
        self.name() == other.name()
    }
    fn attr_matches(
        &self,
        namespace: &NamespaceConstraint<&CssName>,
        name: &CssName,
        operation: &AttrSelectorOperation<&CssString>,
    ) -> bool {
        if matches!(namespace, NamespaceConstraint::Specific(name) if !name.value.is_empty()) {
            return false;
        }
        let Some(actual) = self.attribute(&name.value) else {
            return false;
        };
        // Servo compares an ASCII-insensitive substring at every possible
        // offset. Keep its allocation-free path for short needles, and use
        // Rust's linear-time substring search when the needle is long.
        if let AttrSelectorOperation::WithValue {
            operator: AttrSelectorOperator::Substring,
            case_sensitivity: CaseSensitivity::AsciiCaseInsensitive,
            value,
        } = operation
            && value.0.len() > 32
        {
            return actual.len() >= value.0.len()
                && actual
                    .to_ascii_lowercase()
                    .contains(&value.0.to_ascii_lowercase());
        }
        operation.eval_str(actual)
    }
    fn match_non_ts_pseudo_class(
        &self,
        _pseudo: &NonTSPseudoClass,
        _context: &mut matching::MatchingContext<'_, Css>,
    ) -> bool {
        false
    }
    fn match_pseudo_element(
        &self,
        _pseudo: &PseudoElement,
        _context: &mut matching::MatchingContext<'_, Css>,
    ) -> bool {
        false
    }
    fn apply_selector_flags(&self, _flags: ElementSelectorFlags) {}
    fn is_link(&self) -> bool {
        matches!(self.name(), "a" | "area" | "link") && self.attribute("href").is_some()
    }
    fn is_html_slot_element(&self) -> bool {
        false
    }
    fn has_id(&self, id: &CssName, case: CaseSensitivity) -> bool {
        self.attribute("id")
            .is_some_and(|value| case.eq(id.value.as_bytes(), value.as_bytes()))
    }
    fn has_class(&self, class: &CssName, case: CaseSensitivity) -> bool {
        self.attribute("class").is_some_and(|value| {
            value
                .split([' ', '\t', '\n', '\r', '\u{000c}'])
                .any(|part| case.eq(class.value.as_bytes(), part.as_bytes()))
        })
    }
    fn has_custom_state(&self, _name: &CssName) -> bool {
        false
    }
    fn imported_part(&self, _name: &CssName) -> Option<CssName> {
        None
    }
    fn is_part(&self, _name: &CssName) -> bool {
        false
    }
    fn is_empty(&self) -> bool {
        self.index + 1 == self.tree.nodes[self.index].end
    }
    fn is_root(&self) -> bool {
        self.tree.nodes[self.index].parent.is_none()
    }
    fn add_element_unique_hashes(&self, _filter: &mut BloomFilter) -> bool {
        false
    }
}
