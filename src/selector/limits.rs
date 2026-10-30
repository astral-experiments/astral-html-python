//! Resource limits around Servo's infallible selector-matching interface.
//! The thresholds are heuristics. When tuning them, check both the queries that
//! must finish and the ones that must stop in `tests/test_selector_robustness.py`.

use std::cell::Cell;
use std::panic;

use selectors::attr::CaseSensitivity;
use selectors::matching::SelectorCaches;
use selectors::parser::{Component, Selector};

use super::attributes::equal_bytes;
use super::{Css, CssName, ElementRef, SelectorShape};

// Cancellation must unwind Rust frames, including stacker's extra stack.
#[cfg(panic = "abort")]
compile_error!("astral-html selector limits require the Rust panic=unwind strategy");

// The floor lets a complex selector run on a small subtree. Above 4,096 nodes,
// 64 work units per searched node allow several tests per candidate while
// bounding the repeated walks in a selector such as `:is(.missing ~ i) ~ i`.
const MIN_WORK_BUDGET: usize = 256 * 1024;
const WORK_PER_NODE: usize = 64;

// Servo can short-circuit a wide :is() without visiting most of its branches.
// Charge a visit once per 16 components we cannot observe individually. This
// keeps a short list's per-visit cost low while still weighting wide lists.
const COMPONENTS_PER_WORK_UNIT: usize = 16;

// The 8 MiB floor allows repeated comparisons on small pages. A single
// attribute can exceed that floor, so allow the equivalent of 16 passes over
// retained strings. This admits a scan of a 9 MiB class while bounding
// repeated searches for a missing word in that same class.
const MIN_SCAN_BYTES: usize = 8 * 1024 * 1024;
const SCAN_PASSES: usize = 16;

// The visit charge covers the first 64 bytes of a scan. Comparing names in
// blocks of that size makes a first-block mismatch cheap even on a long name.
pub(super) const SHORT_SCAN: usize = 64;

// Servo 0.41 can retain a 4 KiB Bloom filter per leaf for :has(.x, .y).
// Clear between candidates after 1,024 identity lookups to reuse filters
// without keeping them for the whole tree. A sibling walk can cross that
// threshold before we can clear, so abort past 8,192 lookups since the last clear.
const RELATIVE_CACHE_BATCH: usize = 1024;
const RELATIVE_CACHE_LIMIT: usize = 8192;

// Each :nth-child(... of S) can build its own index. Keep indexes for at least
// 65,536 lookups so small scopes can reuse sibling positions. On larger scopes
// the batch grows with the node count, regardless of the number of selectors.
const MIN_NTH_CACHE_BATCH: usize = 64 * 1024;

/// Upper bound for one of Servo 0.41's relative Bloom filter probes.
#[derive(Default)]
pub(super) struct FilterCost {
    components: usize,
    name_bytes: usize,
}

impl FilterCost {
    pub(super) fn include(&mut self, selector: &Selector<Css>) {
        let mut cost = Self::default();
        let mut hashes = 0;
        cost.count_compound(selector, &mut hashes);
        self.components = self.components.max(cost.components);
        self.name_bytes = self.name_bytes.max(cost.name_bytes);
    }

    fn compare_names(&mut self, name: &CssName, lower: &CssName) -> bool {
        equal_bytes(
            name.value.as_bytes(),
            lower.value.as_bytes(),
            CaseSensitivity::CaseSensitive,
            &mut self.name_bytes,
        )
    }

    fn count_compound(&mut self, selector: &Selector<Css>, hashes: &mut usize) {
        // collect_selector_hashes inspects the rightmost compound until it has
        // four hashes. Only singleton :is() and :where() lists are unfolded.
        for component in selector.iter() {
            if *hashes == 4 {
                break;
            }
            self.components += 1;
            match component {
                Component::LocalName(name) => {
                    *hashes += usize::from(self.compare_names(&name.name, &name.lower_name));
                }
                Component::ID(_)
                | Component::Class(_)
                | Component::DefaultNamespace(_)
                | Component::Namespace(..) => *hashes += 1,
                Component::AttributeInNoNamespaceExists {
                    local_name,
                    local_name_lower,
                } => {
                    self.compare_names(local_name, local_name_lower);
                }
                Component::AttributeOther(attr) => {
                    self.compare_names(&attr.local_name, &attr.local_name_lower);
                }
                Component::Is(list) | Component::Where(list) => {
                    if let [nested] = list.slice() {
                        self.count_compound(nested, hashes);
                    }
                }
                _ => {}
            }
        }
    }
}

/// Count identity lookups, an upper bound on inserts in Servo's private maps.
struct CacheBudget {
    uses: Cell<usize>,
    batch: usize,
    limit: usize,
}

impl CacheBudget {
    fn new(batch: usize, limit: usize) -> Self {
        Self {
            uses: Cell::new(0),
            batch,
            limit,
        }
    }

    fn rotate(&self) -> bool {
        if self.uses.get() < self.batch {
            return false;
        }
        self.uses.set(0);
        true
    }

    fn record(&self, error: &'static str) {
        let uses = self.uses.get();
        if uses >= self.limit {
            cancel(error);
        }
        self.uses.set(uses + 1);
    }
}

pub(super) struct MatchBudget {
    work_left: Cell<usize>,
    scan_bytes_left: Cell<usize>,
    relative_cache: CacheBudget,
    nth_cache: CacheBudget,
    can_build_filter: bool,
    empty_end: Cell<usize>,
}

impl MatchBudget {
    pub(super) fn new(nodes: usize, string_bytes: usize, can_build_filter: bool) -> Self {
        // Eight lookups per node allow several positional tests. The hard
        // limit of two batches leaves room to finish a candidate before clearing.
        let nth_batch = nodes.saturating_mul(8).max(MIN_NTH_CACHE_BATCH);
        Self {
            work_left: Cell::new(nodes.saturating_mul(WORK_PER_NODE).max(MIN_WORK_BUDGET)),
            scan_bytes_left: Cell::new(
                string_bytes.saturating_mul(SCAN_PASSES).max(MIN_SCAN_BYTES),
            ),
            relative_cache: CacheBudget::new(RELATIVE_CACHE_BATCH, RELATIVE_CACHE_LIMIT),
            nth_cache: CacheBudget::new(nth_batch, nth_batch.saturating_mul(2)),
            can_build_filter,
            empty_end: Cell::new(0),
        }
    }

    #[inline]
    pub(super) fn visit(&self, shape: &SelectorShape) {
        // Some nested components, such as universal selectors and logical
        // wrappers, can run wholly inside Servo without an Element callback.
        self.charge_components(shape.unmetered_components);
    }

    #[inline]
    fn charge_components(&self, components: usize) {
        let cost = components.div_ceil(COMPONENTS_PER_WORK_UNIT).max(1);
        let Some(remaining) = self.work_left.get().checked_sub(cost) else {
            cancel("CSS selector exceeded the matching work limit");
        };
        self.work_left.set(remaining);
    }

    #[inline]
    pub(super) fn scan_bytes(&self, bytes: usize) {
        // Short comparisons are already covered by the per-visit work charge.
        if bytes > SHORT_SCAN {
            let Some(remaining) = self.scan_bytes_left.get().checked_sub(bytes - SHORT_SCAN) else {
                cancel("CSS selector exceeded the matching work limit");
            };
            self.scan_bytes_left.set(remaining);
        }
    }

    #[inline]
    pub(super) fn start_element(&self, caches: &mut SelectorCaches) {
        if self.relative_cache.rotate() {
            caches.relative_selector_filter_map = Default::default();
            caches.relative_selector = Default::default();
            self.empty_end.set(0);
        }
        if self.nth_cache.rotate() {
            caches.nth_index = Default::default();
        }
    }

    #[inline]
    pub(super) fn saw_empty_children(&self, index: usize) {
        // A filter can only exist for an anchor already traversed. Keep the
        // latest possible index without allocating a set of all visited nodes.
        self.empty_end.set(self.empty_end.get().max(index + 1));
    }

    #[inline]
    pub(super) fn record_identity(&self, element: &ElementRef<'_>) {
        let shape = element.shape;
        let mut components = shape.unmetered_components;
        // A single match can fill the maps before start_element can rotate them.
        if shape.has_relative {
            self.relative_cache
                .record("CSS selector exceeded the relative-selector cache limit");
            // With no element children, Servo can cache an empty filter and
            // scan selector names without calling our name or attribute tests.
            // Treat a leading text node as possibly text-only to avoid walking
            // the children again on every probe.
            let first = element.index + 1;
            if self.can_build_filter
                && element.index < self.empty_end.get()
                && (first == element.tree.nodes[element.index].end as usize
                    || element.tree.element_name(first).is_none())
            {
                components = components.max(shape.relative_filter.components);
                self.scan_bytes(shape.relative_filter.name_bytes);
            }
        }
        if shape.has_nth_of {
            self.nth_cache
                .record("CSS selector exceeded the nth-index cache limit");
        }
        self.charge_components(components);
    }
}

struct MatchLimit(&'static str);

#[cold]
fn cancel(message: &'static str) -> ! {
    // Servo traversal cannot return an error. Unwind without running the panic
    // hook; inventing a traversal result would corrupt matches and caches.
    panic::resume_unwind(Box::new(MatchLimit(message)))
}

pub(super) fn with_match_limits<T>(query: impl FnOnce() -> T) -> Result<T, String> {
    // Discard results and caches inside stacker's stack, outside Python FFI.
    panic::catch_unwind(panic::AssertUnwindSafe(query)).map_err(|payload| {
        payload
            .downcast::<MatchLimit>()
            .unwrap_or_else(|other| panic::resume_unwind(other))
            .0
            .to_owned()
    })
}
