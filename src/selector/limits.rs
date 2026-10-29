//! Resource limits around Servo's infallible selector-matching interface.

use std::cell::Cell;
use std::panic;

use selectors::matching::SelectorCaches;

use super::SelectorShape;

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
}

impl MatchBudget {
    pub(super) fn new(nodes: usize, string_bytes: usize) -> Self {
        // Servo allocates a separate index map for each :nth-child(... of S).
        // Bound their combined size by the tree, regardless of list width.
        let nth_batch = nodes.saturating_mul(8).max(MIN_NTH_CACHE_BATCH);
        Self {
            // Budget linear scans and allow some complex queries on small trees.
            work_left: Cell::new(nodes.saturating_mul(WORK_PER_NODE).max(MIN_WORK_BUDGET)),
            // Even a single node may need to scan most of the retained strings.
            scan_bytes_left: Cell::new(
                string_bytes
                    .saturating_mul(SCAN_PASSES)
                    .max(MIN_SCAN_BYTES),
            ),
            relative_cache: CacheBudget::new(RELATIVE_CACHE_BATCH, RELATIVE_CACHE_LIMIT),
            nth_cache: CacheBudget::new(nth_batch, nth_batch.saturating_mul(2)),
        }
    }

    #[inline]
    pub(super) fn visit(&self, shape: &SelectorShape) {
        // Some nested components, such as universal selectors and logical
        // wrappers, can run wholly inside Servo without an Element callback.
        let cost = shape
            .unmetered_components
            .div_ceil(COMPONENTS_PER_WORK_UNIT)
            .max(1);
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
        }
        if self.nth_cache.rotate() {
            caches.nth_index = Default::default();
        }
    }

    #[inline]
    pub(super) fn record_identity(&self, shape: &SelectorShape) {
        self.visit(shape);
        // A single match can fill the maps before start_element can rotate them.
        if shape.has_relative {
            self.relative_cache
                .record("CSS selector exceeded the relative-selector cache limit");
        }
        if shape.has_nth_of {
            self.nth_cache
                .record("CSS selector exceeded the nth-index cache limit");
        }
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
