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
            // Budget linear scans and allow some complex queries on small trees.
            work_left: Cell::new(nodes.saturating_mul(WORK_PER_NODE).max(MIN_WORK_BUDGET)),
            // A wide list of simple selectors can match without any Element calls.
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
        // Servo 0.41 can cache a 4 KiB Bloom filter per leaf for two :has()
        // alternatives. Clear only the relative caches between candidates.
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
        // Both relative caches call opaque(). A single match can fill them
        // before we can clear them in start_element.
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
