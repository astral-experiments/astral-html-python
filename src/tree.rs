//! A compact source-order tree built with astral-html's streaming reader.
use std::borrow::Cow;
use std::collections::{HashMap, HashSet};
use std::ops::Range;

use astral_html::{Attribute, Limits, Reader, Token};

pub struct Tree<'a> {
    pub nodes: Vec<Node<'a>>,
    pub attributes: Vec<Attribute<'a>>,
}

pub struct Node<'a> {
    pub kind: Kind<'a>,
    pub parent: Option<usize>,
    pub end: usize,
    pub prev_sibling: Option<usize>,
    pub next_sibling: Option<usize>,
}

pub enum Kind<'a> {
    Element {
        name: Cow<'a, str>,
        attrs: Range<usize>,
    },
    Text(Cow<'a, str>),
}

struct Open<'a> {
    name: Cow<'a, str>,
    retained: Option<usize>,
    last_child: Option<usize>,
    // Previous stack depth with this name, once open_names is in use.
    previous: Option<usize>,
}

impl<'a> Tree<'a> {
    pub fn parse(source: &'a str, tags: Option<&HashSet<String>>) -> Result<Self, &'static str> {
        let limits = Limits::default();
        let mut tree = Self {
            nodes: Vec::with_capacity(16),
            attributes: Vec::new(),
        };
        let mut stack: Vec<Open<'a>> = Vec::new();
        // Like astral_html::Document, index a deep stack only when an end tag
        // mismatches the top. Repeated unmatched tags then need one lookup each.
        let mut open_names: Option<HashMap<Cow<'a, str>, usize>> = None;
        // Open elements track their last retained child; roots share one list.
        let mut last_root = None;
        for token in Reader::new(source) {
            match token {
                Token::StartTag(mut tag) => {
                    let void = is_void(&tag.name);
                    if !void && stack.len() >= limits.max_depth {
                        return Err("HTML document exceeds the nesting limit");
                    }
                    let parent = stack.last().and_then(|entry| entry.retained);
                    let keep = tags.is_none()
                        || parent.is_some()
                        || tags.is_some_and(|tags| tags.contains(tag.name.as_ref()));
                    let mut index = None;
                    if keep {
                        if tree.nodes.len() >= limits.max_nodes {
                            return Err("HTML document exceeds the node limit");
                        }
                        let i = tree.nodes.len();
                        let previous = match stack.last_mut() {
                            Some(entry) if entry.retained.is_some() => &mut entry.last_child,
                            _ => &mut last_root,
                        };
                        let prev_sibling = *previous;
                        *previous = Some(i);
                        if let Some(prev) = prev_sibling {
                            tree.nodes[prev].next_sibling = Some(i);
                        }
                        let start = tree.attributes.len();
                        tree.attributes.append(&mut tag.attributes);
                        tree.nodes.push(Node {
                            kind: Kind::Element {
                                name: tag.name.clone(),
                                attrs: start..tree.attributes.len(),
                            },
                            parent,
                            end: i + 1,
                            prev_sibling,
                            next_sibling: None,
                        });
                        index = Some(i);
                    }
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
                        let end = tree.nodes.len();
                        // Close innermost first to restore shadowed same-name entries.
                        for entry in stack.drain(depth..).rev() {
                            if let Some(index) = entry.retained {
                                tree.nodes[index].end = end;
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
                Token::Text(text) if !text.is_empty() => {
                    let parent = stack.last().and_then(|entry| entry.retained);
                    if tags.is_none() || parent.is_some() {
                        if tree.nodes.len() >= limits.max_nodes {
                            return Err("HTML document exceeds the node limit");
                        }
                        let i = tree.nodes.len();
                        tree.nodes.push(Node {
                            kind: Kind::Text(text),
                            parent,
                            end: i + 1,
                            prev_sibling: None,
                            next_sibling: None,
                        });
                    }
                }
                _ => {}
            }
        }
        let end = tree.nodes.len();
        for entry in stack {
            if let Some(index) = entry.retained {
                tree.nodes[index].end = end;
            }
        }
        Ok(tree)
    }

    /// Detach selected content from the original source, which can then be dropped.
    pub fn into_owned(self) -> Tree<'static> {
        Tree {
            nodes: self
                .nodes
                .into_iter()
                .map(|node| Node {
                    kind: match node.kind {
                        Kind::Element { name, attrs } => Kind::Element {
                            name: Cow::Owned(name.into_owned()),
                            attrs,
                        },
                        Kind::Text(text) => Kind::Text(Cow::Owned(text.into_owned())),
                    },
                    parent: node.parent,
                    end: node.end,
                    prev_sibling: node.prev_sibling,
                    next_sibling: node.next_sibling,
                })
                .collect(),
            attributes: self
                .attributes
                .into_iter()
                .map(|attr| Attribute {
                    name: Cow::Owned(attr.name.into_owned()),
                    value: Cow::Owned(attr.value.into_owned()),
                    // Raw values are not exposed by this interface.
                    raw_value: None,
                })
                .collect(),
        }
    }

    pub fn element_name(&self, index: usize) -> &str {
        match &self.nodes[index].kind {
            Kind::Element { name, .. } => name,
            Kind::Text(_) => unreachable!(),
        }
    }

    pub fn element_attributes(&self, index: usize) -> &[Attribute<'a>] {
        match &self.nodes[index].kind {
            Kind::Element { attrs, .. } => &self.attributes[attrs.clone()],
            Kind::Text(_) => unreachable!(),
        }
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
