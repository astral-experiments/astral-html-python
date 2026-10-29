use std::borrow::Cow;
use std::collections::HashSet;
use std::hash::{DefaultHasher, Hash, Hasher};
use std::ops::Range;
use std::sync::Arc;

use pyo3::exceptions::{PyKeyError, PyUnicodeEncodeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{IntoPyDict, PyAny, PyList, PyMappingProxy, PySlice, PyString};

mod selector;
mod tree;
use tree::{Kind, Tree};

pyo3::create_exception!(
    astral_html,
    InvalidSelectorError,
    PyValueError,
    "The CSS selector is invalid or unsupported."
);
pyo3::create_exception!(
    astral_html,
    ResourceLimitError,
    PyValueError,
    "Parsing HTML or querying the tree exceeded a resource limit."
);

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
// Give __getitem__ only a mapping slot. Otherwise Python tries to iterate an
// Element with integer indices even though attribute lookup requires strings.
#[pyclass(module = "astral_html", frozen, mapping)]
struct Element {
    tree: Arc<Tree>,
    index: usize,
}

enum Traversal {
    DescendantText,
    DirectContent,
}

#[pyclass(module = "astral_html._astral_html", name = "_ContentIterator")]
struct ContentIterator {
    tree: Option<Arc<Tree>>,
    nodes: Range<usize>,
    traversal: Traversal,
}

#[pymethods]
impl ContentIterator {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__<'py>(&mut self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyAny>>> {
        let Some(tree) = &self.tree else {
            return Ok(None);
        };
        match self.traversal {
            Traversal::DescendantText => {
                if let Some(text) = tree.text_in(&mut self.nodes).next() {
                    return Ok(Some(PyString::new(py, text).into_any()));
                }
            }
            Traversal::DirectContent => {
                if let Some(i) = tree.next_child(&mut self.nodes) {
                    let item = match &tree.nodes[i].kind {
                        Kind::Text(span) => PyString::new(py, tree.string(span)).into_any(),
                        Kind::Element { .. } => Bound::new(py, tree.element(i))?.into_any(),
                    };
                    return Ok(Some(item));
                }
            }
        }
        // An exhausted iterator can stay alive without retaining the document.
        self.tree = None;
        Ok(None)
    }
}

impl Element {
    fn content_iterator(&self, traversal: Traversal) -> ContentIterator {
        ContentIterator {
            tree: Some(self.tree.clone()),
            nodes: self.tree.descendants(Some(self.index)),
            traversal,
        }
    }

    fn attribute(&self, name: &Bound<'_, PyString>) -> PyResult<Option<&str>> {
        match name.to_str() {
            Ok(name) => Ok(self
                .tree
                .attribute(self.index, |key| key.eq_ignore_ascii_case(name.as_bytes()))),
            // A surrogate cannot occur in a UTF-8 attribute name.
            Err(err) if err.is_instance_of::<PyUnicodeEncodeError>(name.py()) => Ok(None),
            Err(err) => Err(err),
        }
    }
}

/// Check the byte limit before CPython allocates and caches UTF-8 on the input.
fn bounded_utf8<'a>(
    value: &'a Bound<'_, PyString>,
    limit: usize,
    message: &'static str,
) -> PyResult<&'a str> {
    let py = value.py();
    let str_type = py.get_type::<PyString>();
    // Read the actual length even when a str subclass overrides __len__.
    let chars = if value.is_exact_instance(&str_type) {
        value.len()?
    } else {
        str_type.call_method1(c"__len__", (value,))?.extract()?
    };
    if chars > limit {
        return Err(ResourceLimitError::new_err(message));
    }
    // Small inputs fit at four bytes per character. For large strings near
    // the limit, str.isascii() is constant time and bypasses subclass methods.
    if chars > limit / 4 && !str_type.call_method1(c"isascii", (value,))?.is_truthy()? {
        // Size bounded slices without populating the input's UTF-8 cache.
        // surrogatepass counts unpaired surrogates here; the final strict
        // conversion still reports them against the original string.
        let mut start = 0;
        let mut bytes = 0;
        while bytes + (chars - start) * 4 > limit {
            let end = (start + 8192).min(chars);
            let slice = PySlice::new(py, start as isize, end as isize, 1);
            let chunk = str_type.call_method1(c"__getitem__", (value, slice))?;
            bytes += chunk
                .call_method1(c"encode", ("utf-8", "surrogatepass"))?
                .len()?;
            if bytes + (chars - end) > limit {
                return Err(ResourceLimitError::new_err(message));
            }
            start = end;
        }
    }
    value.to_str()
}

fn select<'a>(
    py: Python<'_>,
    tree: &'a Arc<Tree>,
    root: Option<usize>,
    css: &Bound<'_, PyString>,
    first: bool,
) -> PyResult<impl ExactSizeIterator<Item = Element> + use<'a>> {
    let css = bounded_utf8(
        css,
        selector::MAX_SELECTOR_BYTES,
        selector::SELECTOR_SIZE_ERROR,
    )?;
    let indices = py
        .detach(|| selector::select(tree, root, css, first))
        .map_err(|error| match error {
            selector::SelectError::InvalidSelector(message) => {
                InvalidSelectorError::new_err(message)
            }
            selector::SelectError::ResourceLimit(message) => ResourceLimitError::new_err(message),
        })?;
    Ok(indices.into_iter().map(move |i| tree.element(i)))
}

#[pymethods]
impl Document {
    /// Find all matching elements in source order.
    fn select<'py>(
        &self,
        py: Python<'py>,
        css: &Bound<'_, PyString>,
    ) -> PyResult<Bound<'py, PyList>> {
        PyList::new(py, select(py, &self.tree, None, css, false)?)
    }

    /// Find the first matching element, if any.
    fn select_one(&self, py: Python<'_>, css: &Bound<'_, PyString>) -> PyResult<Option<Element>> {
        Ok(select(py, &self.tree, None, css, true)?.next())
    }
}

#[pymethods]
impl Element {
    /// The ASCII-lowercased tag name.
    #[getter]
    fn tag(&self) -> &str {
        let Kind::Element { name, .. } = &self.tree.nodes[self.index].kind else {
            unreachable!("expected an element");
        };
        // The span points into a UTF-8 string. Slicing it directly avoids
        // revalidating the tag's bytes each time Python reads the property.
        self.tree.string(name)
    }

    /// A read-only mapping of the element's attributes, with ASCII-lowercased keys.
    #[getter]
    fn attrs<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyMappingProxy>> {
        let attrs = self.tree.attributes(self.index).into_py_dict(py)?;
        Ok(PyMappingProxy::new(py, attrs.as_mapping()))
    }

    /// Look up an attribute by ASCII-insensitive name, returning default if absent.
    #[pyo3(signature = (name, default=None))]
    fn get(
        &self,
        py: Python<'_>,
        name: &Bound<'_, PyString>,
        default: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        Ok(match self.attribute(name)? {
            Some(value) => PyString::new(py, value).into_any().unbind(),
            None => default.unwrap_or_else(|| py.None()),
        })
    }

    /// Return whether an attribute is present, ignoring ASCII case.
    fn __contains__(&self, name: &Bound<'_, PyString>) -> PyResult<bool> {
        Ok(self.attribute(name)?.is_some())
    }

    /// Look up a required attribute by ASCII-insensitive name.
    fn __getitem__(&self, name: &Bound<'_, PyString>) -> PyResult<&str> {
        self.attribute(name)?
            .ok_or_else(|| PyKeyError::new_err(name.clone().unbind()))
    }

    /// Descendant text in source order, joined without inserting spaces.
    #[getter]
    fn text(&self) -> Cow<'_, str> {
        let tree = &self.tree;
        let mut segments = tree.text_in(tree.descendants(Some(self.index)));
        let first = segments.next().unwrap_or("");
        // Even nested markup can contain just one text span. Only allocate a
        // Rust string when there are multiple spans to join.
        let Some(second) = segments.next() else {
            return Cow::Borrowed(first);
        };
        let mut text = [first, second].concat();
        text.extend(segments);
        Cow::Owned(text)
    }

    /// Yield descendant text fragments in source order, preserving whitespace.
    fn iter_text(&self) -> ContentIterator {
        self.content_iterator(Traversal::DescendantText)
    }

    /// Yield direct text fragments and child elements in source order.
    fn iter_content(&self) -> ContentIterator {
        self.content_iterator(Traversal::DirectContent)
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
    fn select<'py>(
        &self,
        py: Python<'py>,
        css: &Bound<'_, PyString>,
    ) -> PyResult<Bound<'py, PyList>> {
        PyList::new(py, select(py, &self.tree, Some(self.index), css, false)?)
    }

    /// Find the first matching descendant in source order, or None.
    fn select_one(&self, py: Python<'_>, css: &Bound<'_, PyString>) -> PyResult<Option<Self>> {
        Ok(select(py, &self.tree, Some(self.index), css, true)?.next())
    }

    fn __repr__(&self) -> String {
        format!("<Element {:?}>", self.tag())
    }

    fn __eq__(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.tree, &other.tree) && self.index == other.index
    }

    // With a typed __ne__, PyO3 returns NotImplemented for unrelated types
    // so Python can try the other operand's inequality comparison.
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
    html: &Bound<'_, PyString>,
    retain_subtrees: Option<&Bound<'_, PyAny>>,
) -> PyResult<Document> {
    let html = bounded_utf8(
        html,
        astral_html::Limits::default().max_input_bytes,
        tree::INPUT_SIZE_ERROR,
    )?;
    let tags = retain_subtrees.map(retained_tag_names).transpose()?;
    let tree = py
        .detach(|| Tree::parse(html, tags.as_ref()))
        .map_err(ResourceLimitError::new_err)?;
    Ok(Document {
        tree: Arc::new(tree),
    })
}

// Importing the module requests the GIL by default on free-threaded CPython.
// Parsing and selector matching detach while they work on Rust data.
#[pymodule(gil_used = true)]
fn _astral_html(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add(
        "InvalidSelectorError",
        module.py().get_type::<InvalidSelectorError>(),
    )?;
    module.add(
        "ResourceLimitError",
        module.py().get_type::<ResourceLimitError>(),
    )?;
    module.add_class::<Document>()?;
    module.add_class::<Element>()?;
    module.add_function(wrap_pyfunction!(parse, module)?)?;
    Ok(())
}
