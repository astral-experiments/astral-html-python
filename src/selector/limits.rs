//! One budget per query. A failed charge propagates through the matcher to Python.
//! The thresholds are heuristics. When tuning them, check both the queries that
//! must finish and the ones that must stop in `tests/test_selector_robustness.py`.

pub(super) type MatchResult<T> = Result<T, &'static str>;

const WORK_LIMIT: &str = "CSS selector exceeded the matching work limit";
// The floor lets complex selectors run on small subtrees. Above 4,096 nodes,
// 64 steps per searched node bound repeated walks such as `:is(.missing ~ i) ~ i`.
const MIN_WORK_BUDGET: usize = 256 * 1024;
const WORK_PER_NODE: usize = 64;

// One attribute can exceed the 8 MiB floor. Allow 16 passes over retained
// strings so a long class can be scanned, while repeated searches are bounded.
const MIN_SCAN_BYTES: usize = 8 * 1024 * 1024;
const SCAN_PASSES: usize = 16;
// Comparing names in blocks makes a first-block mismatch cheap on long names.
pub(super) const SHORT_SCAN: usize = 64;

// Reuse :has() results across candidates. A single sibling walk can fill the
// cache before the next candidate, so enforce a hard cap on entries as well.
pub(super) const RELATIVE_CACHE_BATCH: usize = 1024;
pub(super) const RELATIVE_CACHE_LIMIT: usize = 8192;

// Each :nth-child(... of S) can have its own index. Share one batch across
// them all and scale it with the search range on larger trees.
pub(super) const MIN_NTH_CACHE_BATCH: usize = 64 * 1024;

pub(super) struct MatchBudget {
    work_left: usize,
    scan_bytes_left: usize,
}

impl MatchBudget {
    pub(super) fn new(nodes: usize, string_bytes: usize) -> Self {
        Self {
            work_left: nodes.saturating_mul(WORK_PER_NODE).max(MIN_WORK_BUDGET),
            scan_bytes_left: string_bytes.saturating_mul(SCAN_PASSES).max(MIN_SCAN_BYTES),
        }
    }

    #[inline]
    pub(super) fn visit(&mut self) -> MatchResult<()> {
        self.work_left = self.work_left.checked_sub(1).ok_or(WORK_LIMIT)?;
        Ok(())
    }

    #[inline]
    pub(super) fn scan_bytes(&mut self, bytes: usize) -> MatchResult<()> {
        // Short comparisons are already covered by the per-component work charge.
        self.scan_bytes_left = self
            .scan_bytes_left
            .checked_sub(bytes.saturating_sub(SHORT_SCAN))
            .ok_or(WORK_LIMIT)?;
        Ok(())
    }
}
