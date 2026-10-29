//! Attribute selectors can revisit the same long name or value for many candidates.
//! Charge for the portion inspected before a match or mismatch.

use selectors::attr::{
    AttrSelectorOperation, AttrSelectorOperator, CaseSensitivity, SELECTOR_WHITESPACE,
};

use super::limits::SHORT_SCAN;
use super::{CssString, ElementRef};

/// Compare just the common prefix needed to find a mismatch. Record bytes in
/// small blocks so an early difference in a long value is a cheap comparison.
pub(super) fn equal_bytes(a: &[u8], b: &[u8], case: CaseSensitivity, scanned: &mut usize) -> bool {
    if a.len() != b.len() {
        return false;
    }
    if a.len() <= SHORT_SCAN {
        *scanned += a.len();
        return case.eq(a, b);
    }
    a.chunks(SHORT_SCAN)
        .zip(b.chunks(SHORT_SCAN))
        .all(|(a, b)| {
            *scanned += a.len();
            case.eq(a, b)
        })
}

impl ElementRef<'_> {
    pub(super) fn attribute(&self, name: &str) -> Option<&str> {
        self.budget.visit(self.shape);
        let mut scanned = 0;
        let value = self.tree.attribute(self.index, |key| {
            // Visiting a key costs work even if its length rules it out immediately.
            scanned += 1;
            equal_bytes(
                key,
                name.as_bytes(),
                CaseSensitivity::CaseSensitive,
                &mut scanned,
            )
        });
        self.budget.scan_bytes(scanned);
        value
    }
    pub(super) fn bytes_equal(&self, actual: &[u8], needle: &[u8], case: CaseSensitivity) -> bool {
        if actual.len() <= SHORT_SCAN {
            return case.eq(actual, needle);
        }
        let mut scanned = 0;
        let equal = equal_bytes(actual, needle, case, &mut scanned);
        self.budget.scan_bytes(scanned);
        equal
    }
    pub(super) fn has_word(&self, actual: &str, word: &str, case: CaseSensitivity) -> bool {
        if word.is_empty() || word.len() > actual.len() {
            return false;
        }
        if actual.len() <= SHORT_SCAN {
            return AttrSelectorOperator::Includes.eval_str(actual, word, case);
        }
        let mut scanned = 0;
        let found = actual.split(SELECTOR_WHITESPACE).any(|part| {
            scanned += part.len() + 1;
            case.eq(part.as_bytes(), word.as_bytes())
        });
        self.budget.scan_bytes(scanned);
        found
    }
    fn has_substring(&self, mut actual: &str, needle: &str, case: CaseSensitivity) -> bool {
        if needle.is_empty() {
            return false;
        }
        if case == CaseSensitivity::CaseSensitive || needle.len() <= 32 {
            let offset = if case == CaseSensitivity::CaseSensitive {
                actual.find(needle)
            } else {
                actual
                    .as_bytes()
                    .windows(needle.len())
                    .position(|window| window.eq_ignore_ascii_case(needle.as_bytes()))
            };
            self.budget
                .scan_bytes(offset.map_or(actual.len(), |i| i + needle.len()));
            return offset.is_some();
        }
        // Fold long insensitive needles for linear substring search. Start with
        // a short block for early matches, then overlap by a needle's length.
        let folded = needle.to_ascii_lowercase();
        let mut step = SHORT_SCAN.max(needle.len());
        loop {
            let advance = actual.ceil_char_boundary(step.min(actual.len()));
            let end = actual.ceil_char_boundary((advance + needle.len() - 1).min(actual.len()));
            let block = &actual[..end];
            // Lowercasing touches the whole block even if it contains a match.
            self.budget.scan_bytes(block.len());
            let found = block.to_ascii_lowercase().contains(&folded);
            if found || end == actual.len() {
                return found;
            }
            actual = &actual[advance..];
            step = (step * 2).min(4096.max(needle.len()));
        }
    }

    pub(super) fn matches_attribute_value(
        &self,
        actual: &str,
        operation: &AttrSelectorOperation<&CssString>,
    ) -> bool {
        let AttrSelectorOperation::WithValue {
            operator,
            case_sensitivity,
            value,
        } = operation
        else {
            return true;
        };
        let needle = value.as_ref();
        if needle.len() > actual.len() {
            return false;
        }
        if actual.len() <= SHORT_SCAN {
            return operation.eval_str(actual);
        }
        use AttrSelectorOperator::{DashMatch, Equal, Includes, Prefix, Substring, Suffix};
        let bytes = actual.as_bytes();
        let n = needle.len();
        let compared = match operator {
            Includes => return self.has_word(actual, needle, *case_sensitivity),
            Substring => return self.has_substring(actual, needle, *case_sensitivity),
            Equal => bytes,
            Prefix if n > 0 => &bytes[..n],
            Suffix if n > 0 => &bytes[bytes.len() - n..],
            DashMatch if n == bytes.len() || bytes[n] == b'-' => &bytes[..n],
            _ => return false,
        };
        self.bytes_equal(compared, needle.as_bytes(), *case_sensitivity)
    }
}
