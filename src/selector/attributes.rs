//! Attribute selectors can revisit the same long name or value for many candidates.
//! Charge for the portion inspected before a match or mismatch.

use selectors::attr::{
    AttrSelectorOperator, CaseSensitivity, ParsedCaseSensitivity, SELECTOR_WHITESPACE,
};

use super::limits::{MatchResult, SHORT_SCAN};
use super::matching::Matcher;

/// Compare just the common prefix needed to find a mismatch. Record bytes in
/// small blocks so an early difference in a long value is a cheap comparison.
fn equal_bytes(a: &[u8], b: &[u8], case: CaseSensitivity, scanned: &mut usize) -> bool {
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

impl<'tree> Matcher<'tree> {
    pub(super) fn attribute(
        &mut self,
        index: usize,
        name: &str,
    ) -> MatchResult<Option<&'tree str>> {
        let mut scanned = 0;
        let value = self.tree.attribute(index, |key| {
            // Visiting a key costs work even if its length rules it out immediately.
            scanned += 1;
            equal_bytes(
                key,
                name.as_bytes(),
                CaseSensitivity::CaseSensitive,
                &mut scanned,
            )
        });
        self.budget.scan_bytes(scanned)?;
        Ok(value)
    }
    pub(super) fn bytes_equal(
        &mut self,
        actual: &[u8],
        needle: &[u8],
        case: CaseSensitivity,
    ) -> MatchResult<bool> {
        if actual.len() <= SHORT_SCAN {
            return Ok(case.eq(actual, needle));
        }
        let mut scanned = 0;
        let equal = equal_bytes(actual, needle, case, &mut scanned);
        self.budget.scan_bytes(scanned)?;
        Ok(equal)
    }
    pub(super) fn has_word(
        &mut self,
        actual: &str,
        word: &str,
        case: CaseSensitivity,
    ) -> MatchResult<bool> {
        if word.is_empty() || word.len() > actual.len() {
            return Ok(false);
        }
        if actual.len() <= SHORT_SCAN {
            return Ok(AttrSelectorOperator::Includes.eval_str(actual, word, case));
        }
        let mut scanned = 0;
        let found = actual.split(SELECTOR_WHITESPACE).any(|part| {
            scanned += part.len() + 1;
            case.eq(part.as_bytes(), word.as_bytes())
        });
        self.budget.scan_bytes(scanned)?;
        Ok(found)
    }
    fn has_substring(
        &mut self,
        mut actual: &str,
        needle: &str,
        case: CaseSensitivity,
    ) -> MatchResult<bool> {
        if needle.is_empty() {
            return Ok(false);
        }
        // For an insensitive search, comparing up to 32 bytes per offset avoids
        // allocating a lowercase copy. With a longer needle, a shared prefix
        // could make us compare the same bytes many times.
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
                .scan_bytes(offset.map_or(actual.len(), |i| i + needle.len()))?;
            return Ok(offset.is_some());
        }
        // Start small for early matches. Overlap adjacent blocks by at least
        // needle.len() - 1 bytes so matches that cross a boundary are visible.
        let folded = needle.to_ascii_lowercase();
        let mut step = SHORT_SCAN.max(needle.len());
        loop {
            let advance = actual.ceil_char_boundary(step.min(actual.len()));
            let end = actual.ceil_char_boundary((advance + needle.len() - 1).min(actual.len()));
            let block = &actual[..end];
            // Lowercasing touches the whole block even if it contains a match.
            self.budget.scan_bytes(block.len())?;
            let found = block.to_ascii_lowercase().contains(&folded);
            if found || end == actual.len() {
                return Ok(found);
            }
            actual = &actual[advance..];
            // Double the advance on misses to amortize allocations. Cap it at
            // 4 KiB to bound each lowercase copy, or one needle if that's larger.
            step = (step * 2).min(4096.max(needle.len()));
        }
    }

    pub(super) fn matches_attribute_value(
        &mut self,
        index: usize,
        name: &str,
        operator: AttrSelectorOperator,
        needle: &str,
        parsed_case: ParsedCaseSensitivity,
    ) -> MatchResult<bool> {
        let Some(actual) = self.attribute(index, name)? else {
            return Ok(false);
        };
        let case = match parsed_case {
            ParsedCaseSensitivity::ExplicitCaseSensitive | ParsedCaseSensitivity::CaseSensitive => {
                CaseSensitivity::CaseSensitive
            }
            ParsedCaseSensitivity::AsciiCaseInsensitive
            | ParsedCaseSensitivity::AsciiCaseInsensitiveIfInHtmlElementInHtmlDocument => {
                CaseSensitivity::AsciiCaseInsensitive
            }
        };
        if needle.len() > actual.len() {
            return Ok(false);
        }
        if actual.len() <= SHORT_SCAN {
            return Ok(operator.eval_str(actual, needle, case));
        }
        use AttrSelectorOperator::{DashMatch, Equal, Includes, Prefix, Substring, Suffix};
        let bytes = actual.as_bytes();
        let n = needle.len();
        let compared = match operator {
            Includes => return self.has_word(actual, needle, case),
            Substring => return self.has_substring(actual, needle, case),
            Equal => bytes,
            Prefix if n > 0 => &bytes[..n],
            Suffix if n > 0 => &bytes[bytes.len() - n..],
            DashMatch if n == bytes.len() || bytes[n] == b'-' => &bytes[..n],
            _ => return Ok(false),
        };
        self.bytes_equal(compared, needle.as_bytes(), case)
    }
}
