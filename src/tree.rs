//! Source-order nodes link by index. Names, attributes, and text share a UTF-8 buffer.
use std::borrow::Cow;
use std::collections::{HashMap, HashSet};
use std::num::NonZeroU32;
use std::ops::Range;

use astral_html::{Limits, Reader, Token};

pub(crate) const INPUT_SIZE_ERROR: &str = "HTML input exceeds the byte limit";

pub struct Tree {
    pub nodes: Vec<Node>,
    attributes: Vec<(Range<u32>, Range<u32>)>,
    strings: String,
}

pub struct Node {
    pub kind: Kind,
    pub parent: Option<NodeId>,
    pub end: u32,
    pub prev_sibling: Option<NodeId>,
    pub next_sibling: Option<NodeId>,
}

/// One-based so an optional link occupies four bytes, including for text nodes.
#[derive(Clone, Copy)]
pub struct NodeId(NonZeroU32);

impl NodeId {
    fn new(index: usize) -> Self {
        // The parser checks the node limit (four million) before creating an ID.
        Self(NonZeroU32::new(index as u32 + 1).unwrap())
    }

    pub fn index(self) -> usize {
        (self.0.get() - 1) as usize
    }
}

pub enum Kind {
    Element {
        name: Range<u32>,
        // The input byte limit also bounds the number of attributes.
        attrs: Range<u32>,
    },
    Text(Range<u32>),
}

struct Open<'a> {
    name: Cow<'a, str>,
    retained: Option<NodeId>,
    last_child: Option<NodeId>,
    // Previous stack depth with this name, once open_names is in use.
    previous: Option<usize>,
}

impl Tree {
    pub fn parse(source: &str, tags: Option<&HashSet<String>>) -> Result<Self, &'static str> {
        let limits = Limits::default();
        if source.len() > limits.max_input_bytes {
            return Err(INPUT_SIZE_ERROR);
        }
        let max_nodes = limits.max_nodes.min(u32::MAX as usize);
        let single_tag = tags
            .filter(|tags| tags.len() == 1)
            .and_then(|tags| tags.iter().next());
        let mut tree = Self {
            nodes: Vec::with_capacity(16),
            attributes: Vec::new(),
            strings: String::new(),
        };
        // Retained strings share one buffer. The input limit bounds even decoded offsets.
        let mut store = |value: &str| {
            let start = tree.strings.len() as u32;
            tree.strings.push_str(value);
            start..u32::try_from(tree.strings.len()).expect("bounded by the HTML input limit")
        };
        let mut stack: Vec<Open<'_>> = Vec::new();
        // Like astral_html::Document, index a deep stack only when an end tag
        // mismatches the top. Repeated unmatched tags then need one lookup each.
        let mut open_names: Option<HashMap<Cow<'_, str>, usize>> = None;
        // Open elements track their last retained child; roots share one list.
        let mut last_root = None;
        for token in Reader::new(source) {
            let parent = stack.last().and_then(|entry| entry.retained);
            match token {
                Token::StartTag(tag) => {
                    let void = is_void(&tag.name);
                    if !void && stack.len() >= limits.max_depth {
                        return Err("HTML document exceeds the nesting limit");
                    }
                    let keep = parent.is_some()
                        || match single_tag {
                            Some(name) => *name == tag.name,
                            None => tags.is_none_or(|tags| tags.contains(tag.name.as_ref())),
                        };
                    let index = if keep {
                        if tree.nodes.len() >= max_nodes {
                            return Err("HTML document exceeds the node limit");
                        }
                        let id = NodeId::new(tree.nodes.len());
                        let previous = match stack.last_mut() {
                            Some(entry) if entry.retained.is_some() => &mut entry.last_child,
                            _ => &mut last_root,
                        };
                        let prev_sibling = previous.replace(id);
                        if let Some(prev) = prev_sibling {
                            tree.nodes[prev.index()].next_sibling = Some(id);
                        }
                        let start = tree.attributes.len();
                        tree.attributes.extend(
                            tag.attributes
                                .into_iter()
                                .map(|attr| (store(&attr.name), store(&attr.value))),
                        );
                        tree.nodes.push(Node {
                            kind: Kind::Element {
                                name: store(&tag.name),
                                attrs: start as u32..tree.attributes.len() as u32,
                            },
                            parent,
                            end: id.0.get(),
                            prev_sibling,
                            next_sibling: None,
                        });
                        Some(id)
                    } else {
                        None
                    };
                    if !void {
                        let previous = open_names
                            .as_mut()
                            .and_then(|names| names.insert(tag.name.clone(), stack.len()));
                        stack.push(Open {
                            name: tag.name,
                            retained: index,
                            last_child: None,
                            previous,
                        });
                    }
                }
                Token::EndTag(tag) => {
                    let matches_top = stack.last().is_some_and(|entry| entry.name == tag.name);
                    if !matches_top && stack.len() > 8 && open_names.is_none() {
                        let mut names = HashMap::new();
                        for (depth, entry) in stack.iter_mut().enumerate() {
                            entry.previous = names.insert(entry.name.clone(), depth);
                        }
                        open_names = Some(names);
                    }
                    let depth = if matches_top {
                        Some(stack.len() - 1)
                    } else if let Some(names) = &open_names {
                        names.get(tag.name.as_ref()).copied()
                    } else {
                        stack.iter().rposition(|entry| entry.name == tag.name)
                    };
                    if let Some(depth) = depth {
                        let end = tree.nodes.len() as u32;
                        // Close innermost first to restore shadowed same-name entries.
                        for entry in stack.drain(depth..).rev() {
                            if let Some(id) = entry.retained {
                                tree.nodes[id.index()].end = end;
                            }
                            if let Some(names) = &mut open_names {
                                if let Some(previous) = entry.previous {
                                    *names
                                        .get_mut(entry.name.as_ref())
                                        .expect("open name is indexed") = previous;
                                } else {
                                    names.remove(entry.name.as_ref());
                                }
                            }
                        }
                    }
                }
                // Text can only be read through a retained element's subtree.
                Token::Text(text) if parent.is_some() && !text.is_empty() => {
                    let i = tree.nodes.len();
                    if i >= max_nodes {
                        return Err("HTML document exceeds the node limit");
                    }
                    tree.nodes.push(Node {
                        kind: Kind::Text(store(&text)),
                        parent,
                        end: i as u32 + 1,
                        prev_sibling: None,
                        next_sibling: None,
                    });
                }
                _ => {}
            }
        }
        let end = tree.nodes.len() as u32;
        for entry in stack {
            if let Some(id) = entry.retained {
                tree.nodes[id.index()].end = end;
            }
        }
        Ok(tree)
    }

    pub fn string(&self, span: &Range<u32>) -> &str {
        &self.strings[span.start as usize..span.end as usize]
    }

    fn bytes(&self, span: &Range<u32>) -> &[u8] {
        // Match names as bytes; only returned text needs UTF-8 boundary checks.
        &self.strings.as_bytes()[span.start as usize..span.end as usize]
    }

    pub fn element_name(&self, index: usize) -> Option<&[u8]> {
        match &self.nodes[index].kind {
            Kind::Element { name, .. } => Some(self.bytes(name)),
            Kind::Text(_) => None,
        }
    }

    pub fn descendants(&self, root: Option<usize>) -> Range<usize> {
        root.map_or(0..self.nodes.len(), |i| i + 1..self.nodes[i].end as usize)
    }

    pub fn elements_in(
        &self,
        nodes: impl Iterator<Item = usize>,
    ) -> impl Iterator<Item = (usize, &[u8])> {
        nodes.filter_map(|i| self.element_name(i).map(|name| (i, name)))
    }

    pub fn text_in(&self, nodes: impl Iterator<Item = usize>) -> impl Iterator<Item = &str> {
        nodes.filter_map(|i| match &self.nodes[i].kind {
            Kind::Text(span) => Some(self.string(span)),
            Kind::Element { .. } => None,
        })
    }

    /// Direct children, including text nodes.
    pub fn children(&self, index: usize) -> impl Iterator<Item = usize> {
        let mut nodes = self.descendants(Some(index));
        std::iter::from_fn(move || self.next_child(&mut nodes))
    }

    pub fn next_child(&self, nodes: &mut Range<usize>) -> Option<usize> {
        let i = nodes.next()?;
        nodes.start = self.nodes[i].end as usize;
        Some(i)
    }

    fn attribute_spans(&self, index: usize) -> &[(Range<u32>, Range<u32>)] {
        let Kind::Element { attrs, .. } = &self.nodes[index].kind else {
            unreachable!("expected an element")
        };
        &self.attributes[attrs.start as usize..attrs.end as usize]
    }

    pub fn string_bytes(&self) -> usize {
        self.strings.len()
    }

    pub fn attribute(&self, index: usize, mut matches: impl FnMut(&[u8]) -> bool) -> Option<&str> {
        self.attribute_spans(index)
            .iter()
            .find(|(name, _)| matches(self.bytes(name)))
            .map(|(_, value)| self.string(value))
    }

    pub fn attributes(&self, index: usize) -> impl Iterator<Item = (&str, &str)> {
        self.attribute_spans(index)
            .iter()
            .map(|(name, value)| (self.string(name), self.string(value)))
    }
}

fn is_void(name: &str) -> bool {
    matches!(
        name,
        "area"
            | "base"
            | "br"
            | "col"
            | "embed"
            | "hr"
            | "img"
            | "input"
            | "link"
            | "meta"
            | "param"
            | "source"
            | "track"
            | "wbr"
    )
}
