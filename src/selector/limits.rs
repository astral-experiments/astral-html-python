//! Resource limits around Servo's infallible selector-matching interface.

use std::cell::Cell;
use std::panic;

use selectors::matching::SelectorCaches;

use super::SelectorShape;

// Cancelling a match must unwind Rust frames, including stacker's extra stack.
// The release wheels use Rust's default unwind strategy.
#[cfg(panic = "abort")]
compile_error!("astral-html selector limits require the Rust panic=unwind strategy");

const MIN_WORK_BUDGET: usize = 256 * 1024;
const WORK_PER_NODE: usize = 64;
const COMPONENTS_PER_WORK_UNIT: usize = 16;
const RELATIVE_CACHE_BATCH: usize = 1024;
const RELATIVE_CACHE_LIMIT: usize = 8192;

pub(super) struct MatchBudget {
    work_left: Cell<usize>,
    visit_cost: usize,
    relative_cache_uses: Option<Cell<usize>>,
}

impl MatchBudget {
    pub(super) fn new(nodes: usize, shape: SelectorShape) -> Self {
        Self {
            // Allow ordinary linear queries to scale with the search range, and
            // leave room for complex queries over small subtrees.
            work_left: Cell::new(nodes.saturating_mul(WORK_PER_NODE).max(MIN_WORK_BUDGET)),
            // Matching a wide list of simple selectors may make no Element
            // calls. Account for its size, leaving common selectors unweighted.
            visit_cost: shape.components.div_ceil(COMPONENTS_PER_WORK_UNIT).max(1),
            relative_cache_uses: shape.has_relative.then(Cell::default),
        }
    }

    #[inline]
    pub(super) fn visit(&self) {
        let Some(remaining) = self.work_left.get().checked_sub(self.visit_cost) else {
            cancel("CSS selector exceeded the matching work limit");
        };
        self.work_left.set(remaining);
    }

    #[inline]
    pub(super) fn start_element(&self, caches: &mut SelectorCaches) {
        // Servo 0.41 can retain a 4 KiB Bloom filter for every leaf tested
        // against two :has() alternatives. Those filters and relative match
        // results are optional caches: dropping both between candidates is
        // exact, and avoids disturbing the separate positional-selector cache.
        if let Some(uses) = &self.relative_cache_uses
            && uses.get() >= RELATIVE_CACHE_BATCH
        {
            caches.relative_selector_filter_map = Default::default();
            caches.relative_selector = Default::default();
            uses.set(0);
        }
    }

    #[inline]
    pub(super) fn record_identity(&self) {
        self.visit();
        // Both relative cache insertions require Element::opaque(). Count
        // identity requests directly, since a single candidate (for example,
        // a :has() left of a sibling combinator) can populate many entries
        // before we regain access to the caches in start_element.
        if let Some(uses) = &self.relative_cache_uses {
            let n = uses.get();
            if n >= RELATIVE_CACHE_LIMIT {
                cancel("CSS selector exceeded the relative-selector cache limit");
            }
            uses.set(n + 1);
        }
    }
}

struct MatchLimit(&'static str);

#[cold]
fn cancel(message: &'static str) -> ! {
    // Element traversal cannot return an error to Servo. Unwind to our query
    // boundary without invoking the process panic hook. Returning a fake end
    // of the tree instead would corrupt matching and positional caches.
    panic::resume_unwind(Box::new(MatchLimit(message)))
}

pub(super) fn with_match_limits<T>(query: impl FnOnce() -> T) -> Result<T, String> {
    // The closure owns the matching context; cancellation discards all results
    // and caches. Nothing is shared across queries except the immutable tree.
    // In particular this boundary is inside stacker and outside any Python FFI.
    panic::catch_unwind(panic::AssertUnwindSafe(query)).map_err(|payload| {
        payload
            .downcast::<MatchLimit>()
            .unwrap_or_else(|other| panic::resume_unwind(other))
            .0
            .to_owned()
    })
}
