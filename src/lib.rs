use std::collections::HashSet;
use std::hash::{DefaultHasher, Hash, Hasher};
use std::sync::Arc;

use astral_html::Limits;
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyString};
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
    fn with_tree<R>(&self, f: impl FnOnce(&Tree<'_>) -> R) -> R {
        match self {
            Self::Full(parsed) => f(parsed.borrow_dependent()),
            Self::Partial(tree) => f(tree),
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
    storage.with_tree(|tree| {
        let (start, end) = root.map_or((0, tree.nodes.len()), |i| (i + 1, tree.nodes[i].end));
        (start..end)
            .filter(|&i| match &tree.nodes[i].kind {
                Kind::Element { name, .. } => tag.is_none_or(|tag| name.eq_ignore_ascii_case(tag)),
                _ => false,
            })
            .map(|index| Element {
                storage: Arc::clone(storage),
                index,
            })
            .collect()
    })
}

fn select(
    py: Python<'_>,
    storage: &Arc<Storage>,
    root: Option<usize>,
    css: &str,
    first: bool,
) -> PyResult<Vec<Element>> {
    // Matching uses only immutable Rust data. Keep Python conversion (including
    // errors) outside the detached closure; borrowed input remains alive until
    // this synchronous call returns.
    let indices = py
        .detach(|| storage.with_tree(|tree| selector::select(tree, root, css, first)))
        .map_err(PyValueError::new_err)?;
    Ok(indices
        .into_iter()
        .map(|index| Element {
            storage: Arc::clone(storage),
            index,
        })
        .collect())
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
    fn tag(&self) -> String {
        self.storage
            .with_tree(|tree| tree.element_name(self.index).to_owned())
    }

    #[getter]
    fn attrs(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let dict = PyDict::new(py);
        self.storage.with_tree(|tree| {
            for attr in tree.element_attributes(self.index) {
                dict.set_item(attr.name.as_ref(), attr.value.as_ref())?;
            }
            Ok::<_, PyErr>(())
        })?;
        Ok(dict.unbind())
    }

    #[pyo3(signature = (name, default=None))]
    fn get(&self, py: Python<'_>, name: &str, default: Option<Py<PyAny>>) -> Py<PyAny> {
        self.storage.with_tree(|tree| {
            match tree
                .element_attributes(self.index)
                .iter()
                .find(|attr| attr.name.eq_ignore_ascii_case(name))
            {
                Some(attr) => PyString::new(py, &attr.value).into_any().unbind(),
                None => default.unwrap_or_else(|| py.None()),
            }
        })
    }

    #[getter]
    fn text(&self) -> String {
        self.storage.with_tree(|tree| {
            let mut text = String::new();
            for node in &tree.nodes[self.index + 1..tree.nodes[self.index].end] {
                if let Kind::Text(segment) = &node.kind {
                    text.push_str(segment);
                }
            }
            text
        })
    }

    #[getter]
    fn parent(&self) -> Option<Self> {
        self.storage
            .with_tree(|tree| tree.nodes[self.index].parent)
            .map(|index| Self {
                storage: Arc::clone(&self.storage),
                index,
            })
    }

    #[getter]
    fn children(&self) -> Vec<Self> {
        self.storage.with_tree(|tree| {
            let mut result = Vec::new();
            let mut index = self.index + 1;
            while index < tree.nodes[self.index].end {
                let node = &tree.nodes[index];
                if matches!(node.kind, Kind::Element { .. }) {
                    result.push(Self {
                        storage: Arc::clone(&self.storage),
                        index,
                    });
                }
                index = node.end;
            }
            result
        })
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

    // Let Python try the other operand's comparison for unrelated types.
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
        .detach(move || -> Result<Storage, &'static str> {
            match tags {
                Some(tags) => Ok(Storage::Partial(
                    Tree::parse(html, Some(&tags))?.into_owned(),
                )),
                None => Ok(Storage::Full(Parsed::try_new(html.to_owned(), |source| {
                    Tree::parse(source, None)
                })?)),
            }
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
