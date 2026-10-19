//! Adapt Servo's HTML5 tree builder to the compact tree used by Python selectors.
//!
//! `RcDom` is a convenient experimental sink: Servo may reparent nodes during
//! parsing (for example, foster parenting inside tables), so a token stream is
//! insufficient to reproduce the final DOM. A production sink should build a
//! bounded, compact tree directly instead of retaining two complete trees.

use std::collections::HashSet;

use astral_html::Limits;
use html5ever::tendril::TendrilSink;
use html5ever::{ParseOpts, parse_document};
use markup5ever_rcdom::{Handle, NodeData, RcDom};

use super::{Kind, Node, NodeId, Tree};

enum Visit {
    Enter {
        handle: Handle,
        parent: Option<NodeId>,
        depth: usize,
    },
    Leave(NodeId),
}

impl Tree {
    pub fn parse(source: &str, tags: Option<&HashSet<String>>) -> Result<Self, &'static str> {
        let limits = Limits::default();
        if source.len() > limits.max_input_bytes {
            return Err("HTML input exceeds the byte limit");
        }

        // Scraping decoded HTML does not execute scripts. Expose fallback
        // markup under <noscript> so links remain queryable.
        let mut options = ParseOpts::default();
        options.tree_builder.scripting_enabled = false;
        let dom = parse_document(RcDom::default(), options).one(source);
        let mut tree = Self {
            nodes: Vec::new(),
            attributes: Vec::new(),
            strings: String::new(),
        };
        let mut last_children: Vec<Option<NodeId>> = Vec::new();
        let mut last_root = None;
        let mut visits = vec![Visit::Enter {
            handle: dom.document.clone(),
            parent: None,
            depth: 0,
        }];

        while let Some(visit) = visits.pop() {
            let (handle, parent, depth) = match visit {
                Visit::Enter {
                    handle,
                    parent,
                    depth,
                } => (handle, parent, depth),
                Visit::Leave(id) => {
                    tree.nodes[id.index()].end = tree.nodes.len() as u32;
                    continue;
                }
            };
            if depth > limits.max_depth {
                return Err("HTML document exceeds the nesting limit");
            }
            let mut next_parent = parent;
            match &handle.data {
                NodeData::Element { name, attrs, .. } => {
                    let tag = name.local.as_ref();
                    let keep = parent.is_some() || tags.is_none_or(|tags| tags.contains(tag));
                    if keep {
                        if tree.nodes.len() >= limits.max_nodes.min(u32::MAX as usize) {
                            return Err("HTML document exceeds the node limit");
                        }
                        let id = NodeId::new(tree.nodes.len());
                        let previous = match parent {
                            Some(parent) => &mut last_children[parent.index()],
                            None => &mut last_root,
                        };
                        let prev_sibling = previous.replace(id);
                        if let Some(previous) = prev_sibling {
                            tree.nodes[previous.index()].next_sibling = Some(id);
                        }
                        let attrs_start = tree.attributes.len() as u32;
                        for attribute in attrs.borrow().iter() {
                            let key = tree.store(attribute.name.local.as_ref());
                            let value = tree.store(attribute.value.as_ref());
                            tree.attributes.push((key, value));
                        }
                        let name = tree.store(tag);
                        tree.nodes.push(Node {
                            kind: Kind::Element {
                                name,
                                attrs: attrs_start..tree.attributes.len() as u32,
                            },
                            parent,
                            end: id.0.get(),
                            prev_sibling,
                            next_sibling: None,
                        });
                        last_children.push(None);
                        visits.push(Visit::Leave(id));
                        next_parent = Some(id);
                    }
                }
                NodeData::Text { contents } if tags.is_none() || parent.is_some() => {
                    if tree.nodes.len() >= limits.max_nodes.min(u32::MAX as usize) {
                        return Err("HTML document exceeds the node limit");
                    }
                    let span = tree.store(contents.borrow().as_ref());
                    let end = tree.nodes.len() as u32 + 1;
                    tree.nodes.push(Node {
                        kind: Kind::Text(span),
                        parent,
                        end,
                        prev_sibling: None,
                        next_sibling: None,
                    });
                    last_children.push(None);
                }
                NodeData::Document
                | NodeData::Doctype { .. }
                | NodeData::Comment { .. }
                | NodeData::ProcessingInstruction { .. }
                | NodeData::Text { .. } => {}
            }
            for child in handle.children.borrow().iter().rev() {
                visits.push(Visit::Enter {
                    handle: child.clone(),
                    parent: next_parent,
                    depth: depth + 1,
                });
            }
        }
        Ok(tree)
    }

    fn store(&mut self, value: &str) -> std::ops::Range<u32> {
        let start = self.strings.len() as u32;
        self.strings.push_str(value);
        start..self.strings.len() as u32
    }
}
