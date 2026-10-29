//! Resource limits around Servo's infallible selector-matching interface.

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

const MIN_WORK_BUDGET: usize = 256 * 1024;
const WORK_PER_NODE: usize = 64;
const COMPONENTS_PER_WORK_UNIT: usize = 16;
const MIN_SCAN_BYTES: usize = 8 * 1024 * 1024;
const SCAN_PASSES: usize = 16;
pub(super) const SHORT_SCAN: usize = 64;
const RELATIVE_CACHE_BATCH: usize = 1024;
const RELATIVE_CACHE_LIMIT: usize = 8192;
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
        // Servo allocates a separate index map for each :nth-child(... of S).
        // Bound their combined size by the tree, regardless of list width.
        let nth_batch = nodes.saturating_mul(8).max(MIN_NTH_CACHE_BATCH);
        Self {
            // Budget linear scans and allow some complex queries on small trees.
            work_left: Cell::new(nodes.saturating_mul(WORK_PER_NODE).max(MIN_WORK_BUDGET)),
            // Even a single node may need to scan most of the retained strings.
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
        // Servo 0.41 can cache a 4 KiB Bloom filter per leaf for two :has()
        // alternatives. Keep the two types of cache on independent budgets.
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
