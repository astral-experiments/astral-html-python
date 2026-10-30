//! Servo's Element callbacks cannot return errors. Walk the parsed selectors here
//! so a limit reached inside a combinator, :not(), or :nth-child() stops the query.

use std::collections::HashMap;

use selectors::attr::{CaseSensitivity, NamespaceConstraint, ParsedAttrSelectorOperation};
use selectors::parser::{
    Combinator, Component, NthSelectorData, RelativeSelector, RelativeSelectorMatchHint, Selector,
    SelectorIter, SelectorKey,
};
use selectors::{NthIndexCache, OpaqueElement};

use super::Css;
use super::limits::{
    MIN_NTH_CACHE_BATCH, MatchBudget, MatchResult, RELATIVE_CACHE_BATCH, RELATIVE_CACHE_LIMIT,
};
use crate::tree::Tree;

pub(super) struct Matcher<'tree> {
    pub(super) tree: &'tree Tree,
    pub(super) budget: MatchBudget,
    scope: Option<usize>,
    relative: HashMap<(usize, SelectorKey), bool>,
    nth: NthIndexCache,
    nth_inserts: usize,
    nth_batch: usize,
}

impl<'tree> Matcher<'tree> {
    pub(super) fn new(tree: &'tree Tree, scope: Option<usize>) -> Self {
        let nodes = tree.descendants(scope).len();
        Self {
            tree,
            budget: MatchBudget::new(nodes, tree.string_bytes()),
            scope,
            relative: HashMap::new(),
            nth: NthIndexCache::default(),
            nth_inserts: 0,
            nth_batch: nodes.max(MIN_NTH_CACHE_BATCH),
        }
    }

    pub(super) fn select(
        mut self,
        selectors: &[Selector<Css>],
        first: bool,
    ) -> MatchResult<Vec<usize>> {
        // A literal tag in the rightmost compound is required of every match.
        let tag = match selectors {
            [selector] => selector
                .iter()
                .enumerate()
                .find_map(|(i, component)| match component {
                    Component::LocalName(name) => Some((name.lower_name.value.as_bytes(), i == 0)),
                    _ => None,
                }),
            _ => None,
        };
        let offset = usize::from(tag.is_some_and(|(_, first)| first));
        let mut output = Vec::new();
        for (index, name) in self.tree.elements_in(self.tree.descendants(self.scope)) {
            if tag.is_some_and(|(tag, _)| tag != name) {
                continue;
            }
            // Rotate between candidates. A single candidate can still fill a
            // cache, so each insertion also checks its hard limit.
            if self.relative.len() >= RELATIVE_CACHE_BATCH {
                self.relative.clear();
            }
            if self.nth_inserts >= self.nth_batch {
                self.nth = NthIndexCache::default();
                self.nth_inserts = 0;
            }
            for selector in selectors {
                if self.matches(selector.iter_from(offset), index, None)? == Outcome::Matched {
                    output.push(index);
                    if first {
                        return Ok(output);
                    }
                    break;
                }
            }
        }
        Ok(output)
    }

    fn any(
        &mut self,
        selectors: &[Selector<Css>],
        index: usize,
        anchor: Option<usize>,
    ) -> MatchResult<bool> {
        for selector in selectors {
            if self.matches(selector.iter(), index, anchor)? == Outcome::Matched {
                return Ok(true);
            }
        }
        Ok(false)
    }

    fn matches(
        &mut self,
        mut iter: SelectorIter<'_, Css>,
        mut index: usize,
        anchor: Option<usize>,
    ) -> MatchResult<Outcome> {
        for component in &mut iter {
            self.budget.visit()?;
            if !self.simple(component, index, anchor)? {
                return Ok(Outcome::RetrySibling);
            }
        }
        let Some(combinator) = iter.next_sequence() else {
            return Ok(Outcome::Matched);
        };
        loop {
            self.budget.visit()?;
            let node = &self.tree.nodes[index];
            let next = if combinator.is_sibling() {
                node.prev_sibling
            } else {
                node.parent
            };
            let Some(next) = next else {
                return Ok(if combinator.is_sibling() {
                    Outcome::RetryAncestor
                } else {
                    Outcome::Exhausted
                });
            };
            index = next.index();
            let outcome = self.matches(iter.clone(), index, anchor)?;
            match (outcome, combinator) {
                (Outcome::Matched | Outcome::Exhausted, _) => return Ok(outcome),
                (_, Combinator::NextSibling) => return Ok(outcome),
                (_, Combinator::Child) => return Ok(Outcome::RetryAncestor),
                (Outcome::RetryAncestor, Combinator::LaterSibling) => return Ok(outcome),
                _ => {}
            }
        }
    }

    fn simple(
        &mut self,
        component: &Component<Css>,
        index: usize,
        anchor: Option<usize>,
    ) -> MatchResult<bool> {
        use Component::*;
        Ok(match component {
            LocalName(name) => self.bytes_equal(
                self.name(index),
                name.lower_name.value.as_bytes(),
                CaseSensitivity::CaseSensitive,
            )?,
            ID(id) => match self.attribute(index, "id")? {
                Some(value) => self.bytes_equal(
                    value.as_bytes(),
                    id.value.as_bytes(),
                    CaseSensitivity::CaseSensitive,
                )?,
                None => false,
            },
            Class(class) => match self.attribute(index, "class")? {
                Some(value) => {
                    self.has_word(value, &class.value, CaseSensitivity::CaseSensitive)?
                }
                None => false,
            },
            AttributeInNoNamespaceExists {
                local_name_lower, ..
            } => self.attribute(index, &local_name_lower.value)?.is_some(),
            AttributeInNoNamespace {
                local_name,
                operator,
                value,
                case_sensitivity,
            } => self.matches_attribute_value(
                index,
                &local_name.value,
                *operator,
                value.as_ref(),
                *case_sensitivity,
            )?,
            AttributeOther(attr) => {
                if matches!(attr.namespace(), Some(NamespaceConstraint::Specific(ns)) if !ns.value.is_empty())
                {
                    return Ok(false);
                }
                let name = &attr.local_name_lower.value;
                match &attr.operation {
                    ParsedAttrSelectorOperation::Exists => self.attribute(index, name)?.is_some(),
                    ParsedAttrSelectorOperation::WithValue {
                        operator,
                        case_sensitivity,
                        value,
                    } => self.matches_attribute_value(
                        index,
                        name,
                        *operator,
                        value.as_ref(),
                        *case_sensitivity,
                    )?,
                }
            }
            ExplicitUniversalType | ExplicitAnyNamespace | ExplicitNoNamespace => true,
            Namespace(_, ns) | DefaultNamespace(ns) => ns.value.is_empty(),
            Root => self.tree.nodes[index].parent.is_none(),
            Empty => index + 1 == self.tree.nodes[index].end as usize,
            Scope | ImplicitScope | ParentSelector => self.scope.map_or_else(
                || self.tree.nodes[index].parent.is_none(),
                |root| root == index,
            ),
            RelativeSelectorAnchor => anchor == Some(index),
            Is(list) | Where(list) => self.any(list.slice(), index, anchor)?,
            Negation(list) => !self.any(list.slice(), index, anchor)?,
            Has(list) => {
                if anchor.is_some() {
                    return Ok(false);
                }
                for relative in list {
                    if self.relative_matches(relative, index)? {
                        return Ok(true);
                    }
                }
                false
            }
            Nth(data) => self.nth_matches(data, &[], index, anchor)?,
            NthOf(data) => self.nth_matches(data.nth_data(), data.selectors(), index, anchor)?,
            Invalid(..) | Host(_) | Slotted(_) | Part(_) | PseudoElement(_)
            | NonTSPseudoClass(_) | Combinator(_) => false,
        })
    }

    fn name(&self, index: usize) -> &'tree [u8] {
        self.tree.element_name(index).expect("expected an element")
    }

    fn relative_matches(
        &mut self,
        relative: &RelativeSelector<Css>,
        index: usize,
    ) -> MatchResult<bool> {
        self.budget.visit()?;
        let key = (index, SelectorKey::new(&relative.selector));
        if let Some(&matched) = self.relative.get(&key) {
            return Ok(matched);
        }
        if self.relative.len() >= RELATIVE_CACHE_LIMIT {
            return Err("CSS selector exceeded the relative-selector cache limit");
        }
        let matched = self.search_relative(relative, index)?;
        self.relative.insert(key, matched);
        Ok(matched)
    }

    fn search_relative(
        &mut self,
        relative: &RelativeSelector<Css>,
        index: usize,
    ) -> MatchResult<bool> {
        let hint = relative.match_hint;
        let tree = self.tree;
        if hint.is_descendant_direction() {
            return if matches!(hint, RelativeSelectorMatchHint::InChild) {
                self.search_nodes(tree.children(index), relative, index)
            } else {
                self.search_nodes(tree.descendants(Some(index)), relative, index)
            };
        }
        let mut sibling = self.tree.nodes[index].next_sibling;
        while let Some(id) = sibling {
            self.budget.visit()?;
            let i = id.index();
            if hint.is_subtree() {
                if self.search_nodes(tree.descendants(Some(i)), relative, index)? {
                    return Ok(true);
                }
            } else if self.matches(relative.selector.iter(), i, Some(index))? == Outcome::Matched {
                return Ok(true);
            }
            if hint.is_next_sibling() {
                break;
            }
            sibling = self.tree.nodes[i].next_sibling;
        }
        Ok(false)
    }

    fn search_nodes(
        &mut self,
        nodes: impl Iterator<Item = usize>,
        relative: &RelativeSelector<Css>,
        anchor: usize,
    ) -> MatchResult<bool> {
        for node in nodes {
            self.budget.visit()?;
            if self.tree.element_name(node).is_some()
                && self.matches(relative.selector.iter(), node, Some(anchor))? == Outcome::Matched
            {
                return Ok(true);
            }
        }
        Ok(false)
    }

    fn nth_matches(
        &mut self,
        data: &NthSelectorData,
        selectors: &[Selector<Css>],
        index: usize,
        anchor: Option<usize>,
    ) -> MatchResult<bool> {
        let of_type = data.ty.is_of_type();
        let from_end = data.ty.is_from_end();
        if data.ty.is_only() {
            return Ok(
                self.nth_matches(&NthSelectorData::first(of_type), &[], index, anchor)?
                    && self.nth_matches(&NthSelectorData::last(of_type), &[], index, anchor)?,
            );
        }
        let node = &self.tree.nodes[index];
        if data.is_simple_edge() && selectors.is_empty() {
            return Ok(if from_end {
                node.next_sibling
            } else {
                node.prev_sibling
            }
            .is_none());
        }
        if !selectors.is_empty() && !self.any(selectors, index, anchor)? {
            return Ok(false);
        }
        let opaque = OpaqueElement::new(node);
        if let Some(rank) = self.nth.get(of_type, from_end, selectors).lookup(opaque) {
            return Ok(data.an_plus_b.matches_index(rank));
        }

        let rank = self.nth_rank(data, selectors, index, anchor)?;
        // We clear indexes between candidates. A second batch leaves room for
        // a sibling walk that crosses the threshold before the next clear.
        if self.nth_inserts >= self.nth_batch.saturating_mul(2) {
            return Err("CSS selector exceeded the nth-index cache limit");
        }
        self.nth
            .get(of_type, from_end, selectors)
            .insert(opaque, rank);
        self.nth_inserts += 1;
        Ok(data.an_plus_b.matches_index(rank))
    }

    fn nth_rank(
        &mut self,
        data: &NthSelectorData,
        selectors: &[Selector<Css>],
        index: usize,
        anchor: Option<usize>,
    ) -> MatchResult<i32> {
        let of_type = data.ty.is_of_type();
        let from_end = data.ty.is_from_end();
        let has_cached_rank = !self.nth.get(of_type, from_end, selectors).is_empty();
        let tree = self.tree;
        // Count matching siblings until a cached rank or the end of the list.
        let mut walk = |left: bool| -> MatchResult<(i32, Option<i32>)> {
            let mut distance = 0;
            let mut node = &tree.nodes[index];
            while let Some(id) = if left {
                node.prev_sibling
            } else {
                node.next_sibling
            } {
                self.budget.visit()?;
                let sibling = id.index();
                node = &tree.nodes[sibling];
                if of_type
                    && !self.bytes_equal(
                        self.name(index),
                        self.name(sibling),
                        CaseSensitivity::CaseSensitive,
                    )?
                {
                    continue;
                }
                if !selectors.is_empty() && !self.any(selectors, sibling, anchor)? {
                    continue;
                }
                distance += 1;
                if let Some(rank) = self
                    .nth
                    .get(of_type, from_end, selectors)
                    .lookup(OpaqueElement::new(node))
                {
                    return Ok((distance, Some(rank)));
                }
            }
            Ok((distance, None))
        };
        // In source order the previous matching sibling often has a cached
        // rank from the end. Subtracting the distance avoids rescanning the suffix.
        if from_end
            && has_cached_rank
            && let (distance, Some(rank)) = walk(true)?
        {
            return Ok(rank - distance);
        }
        let (distance, rank) = walk(!from_end)?;
        Ok(distance + rank.unwrap_or(1))
    }
}

// If an ancestor search has already exhausted the tree, trying earlier siblings
// cannot help. Preserve that information when backtracking over mixed combinators.
#[derive(Clone, Copy, PartialEq)]
enum Outcome {
    Matched,
    RetrySibling,
    RetryAncestor,
    Exhausted,
}
