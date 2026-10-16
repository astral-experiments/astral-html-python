use std::borrow::Cow;
use std::collections::HashSet;
use std::hash::{DefaultHasher, Hash, Hasher};
use std::sync::Arc;

use astral_html::Limits;
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{IntoPyDict, PyAny, PyDict, PyString};
use self_cell::self_cell;

mod selector;
mod tree;
use tree::{Kind, Tree};

self_cell!(
    struct Parsed {
        owner: String,
        #[covariant]
        dependent: Tree,
    }
);

enum Storage {
    Full(Parsed),
    Partial(Tree<'static>),
}

impl Storage {
    fn tree(&self) -> &Tree<'_> {
        match self {
            Self::Full(parsed) => parsed.borrow_dependent(),
            Self::Partial(tree) => tree,
        }
    }

    fn element(self: &Arc<Self>, index: usize) -> Element {
        Element {
            storage: self.clone(),
            index,
        }
    }
}

#[pyclass(module = "astral_html", frozen)]
struct Document {
    storage: Arc<Storage>,
}

#[pyclass(module = "astral_html", frozen)]
struct Element {
    storage: Arc<Storage>,
    index: usize,
}

fn elements(storage: &Arc<Storage>, root: Option<usize>, tag: Option<&str>) -> Vec<Element> {
    let tree = storage.tree();
    tree.elements_in(tree.descendants(root))
        .filter(|(_, name)| tag.is_none_or(|tag| name.eq_ignore_ascii_case(tag)))
        .map(|(i, _)| storage.element(i))
        .collect()
}

fn select(
    py: Python<'_>,
    storage: &Arc<Storage>,
    root: Option<usize>,
    css: &str,
    first: bool,
) -> PyResult<Vec<Element>> {
    let indices = py
        .detach(|| selector::select(storage.tree(), root, css, first))
        .map_err(PyValueError::new_err)?;
    Ok(indices.into_iter().map(|i| storage.element(i)).collect())
}

#[pymethods]
impl Document {
    /// Return all retained elements in source order, optionally filtered by tag.
    #[pyo3(signature = (tag=None))]
    fn elements(&self, py: Python<'_>, tag: Option<&str>) -> Vec<Element> {
        py.detach(|| elements(&self.storage, None, tag))
    }

    /// Find all matching elements in source order.
    fn select(&self, py: Python<'_>, css: &str) -> PyResult<Vec<Element>> {
        select(py, &self.storage, None, css, false)
    }

    /// Find the first matching element, if any.
    fn select_one(&self, py: Python<'_>, css: &str) -> PyResult<Option<Element>> {
        Ok(select(py, &self.storage, None, css, true)?
            .into_iter()
            .next())
    }
}

#[pymethods]
impl Element {
    #[getter]
    fn tag(&self) -> &str {
        self.storage.tree().nodes[self.index]
            .element_name()
            .expect("expected an element")
    }

    #[getter]
    fn attrs<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        self.storage.tree().attributes(self.index).into_py_dict(py)
    }

    #[pyo3(signature = (name, default=None))]
    fn get(&self, py: Python<'_>, name: &str, default: Option<Py<PyAny>>) -> Py<PyAny> {
        match self
            .storage
            .tree()
            .attributes(self.index)
            .find(|(key, _)| key.eq_ignore_ascii_case(name))
        {
            Some((_, value)) => PyString::new(py, value).into_any().unbind(),
            None => default.unwrap_or_else(|| py.None()),
        }
    }

    #[getter]
    fn text(&self) -> String {
        let tree = self.storage.tree();
        let mut text = String::new();
        for node in &tree.nodes[tree.descendants(Some(self.index))] {
            if let Kind::Text(segment) = &node.kind {
                text.push_str(segment);
            }
        }
        text
    }

    #[getter]
    fn parent(&self) -> Option<Self> {
        self.storage.tree().nodes[self.index]
            .parent
            .map(|i| self.storage.element(i))
    }

    #[getter]
    fn children(&self) -> Vec<Self> {
        let tree = self.storage.tree();
        tree.elements_in(tree.children(self.index))
            .map(|(i, _)| self.storage.element(i))
            .collect()
    }

    #[pyo3(signature = (tag=None))]
    fn elements(&self, py: Python<'_>, tag: Option<&str>) -> Vec<Self> {
        py.detach(|| elements(&self.storage, Some(self.index), tag))
    }

    fn select(&self, py: Python<'_>, css: &str) -> PyResult<Vec<Self>> {
        select(py, &self.storage, Some(self.index), css, false)
    }

    fn select_one(&self, py: Python<'_>, css: &str) -> PyResult<Option<Self>> {
        Ok(select(py, &self.storage, Some(self.index), css, true)?
            .into_iter()
            .next())
    }

    fn __repr__(&self) -> String {
        format!("<Element {:?}>", self.tag())
    }

    fn __eq__(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.storage, &other.storage) && self.index == other.index
    }

    fn __ne__(&self, other: &Self) -> bool {
        !self.__eq__(other)
    }

    fn __hash__(&self) -> isize {
        let mut hasher = DefaultHasher::new();
        Arc::as_ptr(&self.storage).hash(&mut hasher);
        self.index.hash(&mut hasher);
        hasher.finish() as isize
    }
}

/// Parse decoded HTML; when tags is supplied, retain only matching subtrees.
#[pyfunction(signature = (html, *, tags=None))]
fn parse(py: Python<'_>, html: &str, tags: Option<Bound<'_, PyAny>>) -> PyResult<Document> {
    let tags: Option<HashSet<String>> = match tags {
        Some(tags) => {
            if tags.cast::<PyString>().is_ok() {
                return Err(PyTypeError::new_err(
                    "tags must be an iterable of tag names, not a string",
                ));
            }
            let mut names = HashSet::new();
            for tag in tags.try_iter()? {
                let tag = tag?.extract::<String>()?;
                if tag.is_empty() {
                    return Err(PyValueError::new_err("tag names must not be empty"));
                }
                names.insert(tag.to_ascii_lowercase());
            }
            Some(names)
        }
        None => None,
    };
    if html.len() > Limits::default().max_input_bytes {
        return Err(PyValueError::new_err("HTML input exceeds the byte limit"));
    }
    let storage = py
        .detach(move || match tags {
            Some(tags) => {
                Tree::parse(html, Some(&tags), |s| Cow::Owned(s.into_owned())).map(Storage::Partial)
            }
            None => Parsed::try_new(html.to_owned(), |source| {
                Tree::parse(source, None, std::convert::identity)
            })
            .map(Storage::Full),
        })
        .map_err(PyValueError::new_err)?;
    Ok(Document {
        storage: Arc::new(storage),
    })
}

#[pymodule(gil_used = true)]
fn _astral_html(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<Document>()?;
    module.add_class::<Element>()?;
    module.add_function(wrap_pyfunction!(parse, module)?)?;
    Ok(())
}
