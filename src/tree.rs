//! A compact source-order tree built with astral-html's streaming reader.
use std::borrow::Cow;
use std::collections::{HashMap, HashSet};
use std::ops::Range;

use astral_html::{Limits, Reader, Token};

pub struct Tree<'a> {
    pub nodes: Vec<Node<'a>>,
    attributes: Vec<(Cow<'a, str>, Cow<'a, str>)>,
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

impl Node<'_> {
    pub fn element_name(&self) -> Option<&str> {
        match &self.kind {
            Kind::Element { name, .. } => Some(name),
            Kind::Text(_) => None,
        }
    }
}

struct Open<'a> {
    name: Cow<'a, str>,
    retained: Option<usize>,
    last_child: Option<usize>,
    // Previous stack depth with this name, once open_names is in use.
    previous: Option<usize>,
}

impl<'a> Tree<'a> {
    /// Full trees borrow strings from their source. Partial trees copy retained strings here.
    pub fn parse<'input>(
        source: &'input str,
        tags: Option<&HashSet<String>>,
        store: impl Fn(Cow<'input, str>) -> Cow<'a, str>,
    ) -> Result<Self, &'static str> {
        let limits = Limits::default();
        let mut tree = Self {
            nodes: Vec::with_capacity(16),
            attributes: Vec::new(),
        };
        let mut stack: Vec<Open<'input>> = Vec::new();
        // Like astral_html::Document, index a deep stack only when an end tag
        // mismatches the top. Repeated unmatched tags then need one lookup each.
        let mut open_names: Option<HashMap<Cow<'input, str>, usize>> = None;
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
                        || tags.is_none_or(|tags| tags.contains(tag.name.as_ref()));
                    let index = if keep {
                        if tree.nodes.len() >= limits.max_nodes {
                            return Err("HTML document exceeds the node limit");
                        }
                        let i = tree.nodes.len();
                        let previous = match stack.last_mut() {
                            Some(entry) if entry.retained.is_some() => &mut entry.last_child,
                            _ => &mut last_root,
                        };
                        let prev_sibling = previous.replace(i);
                        if let Some(prev) = prev_sibling {
                            tree.nodes[prev].next_sibling = Some(i);
                        }
                        let start = tree.attributes.len();
                        tree.attributes.extend(
                            tag.attributes
                                .into_iter()
                                .map(|attr| (store(attr.name), store(attr.value))),
                        );
                        tree.nodes.push(Node {
                            kind: Kind::Element {
                                name: store(tag.name.clone()),
                                attrs: start..tree.attributes.len(),
                            },
                            parent,
                            end: i + 1,
                            prev_sibling,
                            next_sibling: None,
                        });
                        Some(i)
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
                Token::Text(text) if !text.is_empty() && (tags.is_none() || parent.is_some()) => {
                    let i = tree.nodes.len();
                    if i >= limits.max_nodes {
                        return Err("HTML document exceeds the node limit");
                    }
                    tree.nodes.push(Node {
                        kind: Kind::Text(store(text)),
                        parent,
                        end: i + 1,
                        prev_sibling: None,
                        next_sibling: None,
                    });
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

    pub fn descendants(&self, root: Option<usize>) -> Range<usize> {
        root.map_or(0..self.nodes.len(), |i| i + 1..self.nodes[i].end)
    }

    pub fn elements_in(
        &self,
        nodes: impl Iterator<Item = usize>,
    ) -> impl Iterator<Item = (usize, &str)> {
        nodes.filter_map(|i| self.nodes[i].element_name().map(|name| (i, name)))
    }

    /// Direct children, including text nodes.
    pub fn children(&self, index: usize) -> impl Iterator<Item = usize> {
        let mut nodes = self.descendants(Some(index));
        std::iter::from_fn(move || {
            let i = nodes.next()?;
            nodes.start = self.nodes[i].end;
            Some(i)
        })
    }

    pub fn attributes(&self, index: usize) -> impl Iterator<Item = (&str, &str)> {
        let Kind::Element { attrs, .. } = &self.nodes[index].kind else {
            unreachable!("expected an element")
        };
        self.attributes[attrs.clone()]
            .iter()
            .map(|(name, value)| (name.as_ref(), value.as_ref()))
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
