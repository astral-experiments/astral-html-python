use std::borrow::Cow;
use std::collections::HashSet;
use std::hash::{DefaultHasher, Hash, Hasher};
use std::sync::Arc;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{IntoPyDict, PyAny, PyDict, PyList, PyString};

mod selector;
mod tree;
use tree::{Kind, Tree};

impl Tree {
    fn element(self: &Arc<Self>, index: usize) -> Element {
        Element {
            tree: self.clone(),
            index,
        }
    }
}

/// A parsed HTML tree. Its elements are returned in source order.
#[pyclass(module = "astral_html", frozen)]
struct Document {
    tree: Arc<Tree>,
}

/// A handle to a node that keeps its parsed tree alive.
#[pyclass(module = "astral_html", frozen)]
struct Element {
    tree: Arc<Tree>,
    index: usize,
}

fn select<'a>(
    py: Python<'_>,
    tree: &'a Arc<Tree>,
    root: Option<usize>,
    css: &str,
    first: bool,
) -> PyResult<impl ExactSizeIterator<Item = Element> + use<'a>> {
    let indices = py
        .detach(|| selector::select(tree, root, css, first))
        .map_err(PyValueError::new_err)?;
    Ok(indices.into_iter().map(move |i| tree.element(i)))
}

#[pymethods]
impl Document {
    /// Find all matching elements in source order.
    fn select<'py>(&self, py: Python<'py>, css: &str) -> PyResult<Bound<'py, PyList>> {
        PyList::new(py, select(py, &self.tree, None, css, false)?)
    }

    /// Find the first matching element, if any.
    fn select_one(&self, py: Python<'_>, css: &str) -> PyResult<Option<Element>> {
        Ok(select(py, &self.tree, None, css, true)?.next())
    }
}

#[pymethods]
impl Element {
    /// The ASCII-lowercased tag name.
    #[getter]
    fn tag(&self) -> &str {
        let name = self
            .tree
            .element_name(self.index)
            .expect("expected an element");
        std::str::from_utf8(name).expect("tag names are UTF-8")
    }

    /// A new dictionary of attributes. Changes to it do not affect the tree.
    #[getter]
    fn attrs<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        self.tree.attributes(self.index).into_py_dict(py)
    }

    /// Look up an attribute by ASCII-insensitive name, returning default if absent.
    #[pyo3(signature = (name, default=None))]
    fn get(&self, py: Python<'_>, name: &str, default: Option<Py<PyAny>>) -> Py<PyAny> {
        match self
            .tree
            .attribute(self.index, |key| key.eq_ignore_ascii_case(name.as_bytes()))
        {
            Some(value) => PyString::new(py, value).into_any().unbind(),
            None => default.unwrap_or_else(|| py.None()),
        }
    }

    /// Descendant text in source order, joined without inserting spaces.
    #[getter]
    fn text(&self) -> Cow<'_, str> {
        let tree = &self.tree;
        let mut segments = tree.nodes[tree.descendants(Some(self.index))]
            .iter()
            .filter_map(|node| match &node.kind {
                Kind::Text(segment) => Some(tree.string(segment)),
                _ => None,
            });
        let first = segments.next().unwrap_or("");
        let Some(second) = segments.next() else {
            return Cow::Borrowed(first);
        };
        let mut text = [first, second].concat();
        text.extend(segments);
        Cow::Owned(text)
    }

    /// The parent element, or None for a root of the retained tree.
    #[getter]
    fn parent(&self) -> Option<Self> {
        self.tree.nodes[self.index]
            .parent
            .map(|id| self.tree.element(id.index()))
    }

    /// Direct child elements in source order.
    #[getter]
    fn children(&self) -> Vec<Self> {
        let tree = &self.tree;
        tree.elements_in(tree.children(self.index))
            .map(|(i, _)| tree.element(i))
            .collect()
    }

    /// Find matching descendants. Use :scope in the selector to refer to this element.
    fn select<'py>(&self, py: Python<'py>, css: &str) -> PyResult<Bound<'py, PyList>> {
        PyList::new(py, select(py, &self.tree, Some(self.index), css, false)?)
    }

    /// Find the first matching descendant in source order, or None.
    fn select_one(&self, py: Python<'_>, css: &str) -> PyResult<Option<Self>> {
        Ok(select(py, &self.tree, Some(self.index), css, true)?.next())
    }

    fn __repr__(&self) -> String {
        format!("<Element {:?}>", self.tag())
    }

    fn __eq__(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.tree, &other.tree) && self.index == other.index
    }

    fn __ne__(&self, other: &Self) -> bool {
        !self.__eq__(other)
    }

    fn __hash__(&self) -> isize {
        let mut hasher = DefaultHasher::new();
        Arc::as_ptr(&self.tree).hash(&mut hasher);
        self.index.hash(&mut hasher);
        hasher.finish() as isize
    }
}

fn retained_tag_names(value: &Bound<'_, PyAny>) -> PyResult<HashSet<String>> {
    fn tag_name(value: &Bound<'_, PyAny>) -> PyResult<String> {
        let name = value.extract::<&str>()?;
        if name.is_empty() {
            return Err(PyValueError::new_err("tag names must not be empty"));
        }
        Ok(name.to_ascii_lowercase())
    }

    if value.is_instance_of::<PyString>() {
        return Ok(HashSet::from([tag_name(value)?]));
    }
    value.try_iter()?.map(|tag| tag_name(&tag?)).collect()
}

/// Parse decoded HTML, optionally retaining only subtrees rooted at the named tags.
#[pyfunction(signature = (html, *, retain_subtrees=None))]
fn parse(
    py: Python<'_>,
    html: &str,
    retain_subtrees: Option<&Bound<'_, PyAny>>,
) -> PyResult<Document> {
    let tags = retain_subtrees.map(retained_tag_names).transpose()?;
    let tree = py
        .detach(|| Tree::parse(html, tags.as_ref()))
        .map_err(PyValueError::new_err)?;
    Ok(Document {
        tree: Arc::new(tree),
    })
}

#[pymodule(gil_used = true)]
fn _astral_html(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<Document>()?;
    module.add_class::<Element>()?;
    module.add_function(wrap_pyfunction!(parse, module)?)?;
    Ok(())
}
