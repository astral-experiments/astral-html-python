# Stable ABI versus version-specific wheels

The default wheels are `cp314-cp314` and `cp315-cp315`. Enable the `abi3` build
feature to produce a single `cp314-abi3` wheel for both versions of GIL-enabled
CPython. The benchmark compares these wheels on the same pages.

## October 29 results

For a full scrape of link URLs and text, ABI3 took 0.2% longer on CPython 3.14
and 0.2% less time on 3.15. Both intervals fall within the experiment’s ±5%
practical equivalence range. Counting element tags with `doc.select("*")` took
6.0% and 7.3% longer with ABI3. Both histogram intervals cross +5%.

Native times are mean microseconds per page ± standard error. The ABI3
columns give the change in elapsed time with paired 95% confidence intervals.
Positive values mean the ABI3 wheel took longer.

| Python workload | 3.14 native, µs | 3.14 ABI3 change (95% CI) | 3.15 native, µs | 3.15 ABI3 change (95% CI) |
| --- | ---: | ---: | ---: | ---: |
| Parse + extract link URLs and text | 472.8 ± 4.7 | +0.2% (−1.2 to +1.5%) | 466.7 ± 4.1 | −0.2% (−1.2 to +0.9%) |
| Parse retaining only links + extract URLs and text | 423.8 ± 3.8 | +0.2% (−0.8 to +1.1%) | 421.7 ± 3.7 | −0.7% (−1.7 to +0.3%) |
| Extract link URLs and text from a parsed tree | 69.4 ± 0.7 | +2.1% (+0.3 to +3.9%) | 66.4 ± 0.4 | +4.9% (+3.2 to +6.5%) |
| Parse and release document | 406.9 ± 3.9 | −0.5% (−1.3 to +0.3%) | 430.6 ± 27.5 | −5.6% (−13.8 to −0.5%) |
| Parse + read page metadata | 418.6 ± 4.2 | +0.7% (−0.2 to +1.7%) | 420.1 ± 4.5 | −1.5% (−3.3 to +0.2%) |
| Parse + extract headings and paragraphs | 539.4 ± 4.0 | +0.7% (−0.1 to +1.6%) | 536.9 ± 4.6 | −0.5% (−1.6 to +0.6%) |
| Count elements by tag on a parsed tree | 198.8 ± 1.0 | +6.0% (+4.7 to +7.2%) | 201.1 ± 1.1 | +7.3% (+3.9 to +12.3%) |

The CPython 3.15 parse-only estimate is sensitive to one pair. The native
wheel took 946 µs/page in pair 2 and less than 437 µs/page in every other
pair. The table includes all 20 pairs. [3.14 observations](wheel-abi-samples/2026-10-29-cp314.json) ·
[3.15 observations](wheel-abi-samples/2026-10-29-cp315.json)

These 0.0.1 wheels were built from the same source distribution and ran on
logical CPU 8 of a Linux x86-64 AMD EPYC Milan VM. The observations record each
wheel’s SHA-256. The source distribution’s SHA-256 was
`b6d58b708ad1c575d9b732547c86c50c496087d76e5f5ab1d5588b7154ad55b8`.
[Wheel sources at `98a6a38`](https://github.com/astral-experiments/astral-html-python/tree/98a6a38dcc5e3f85e77a11139e38927d511430a4)

## Historical results at `4ba2c2f`

Before timing, we set a practical equivalence range of ±5%. With ABI3 on
this revision, parsing a page and extracting
every link and its text took 1.0% longer on CPython 3.14 and 2.1% longer on 3.15.
Counting every element by tag took 7.0% and 7.9% longer, with both 95% intervals
entirely above our 5% threshold.
ABI3 was slower in all 20 pairs on each Python version for that task. It calls
`doc.elements()`, reads each element’s `tag` in Python, and counts the tags with
`collections.Counter`. The current API uses `doc.select("*")` to enumerate
elements, so the historical histogram measures a different operation.

| Python workload | 3.14 native, µs | 3.14 ABI3 change (95% CI) | 3.15 native, µs | 3.15 ABI3 change (95% CI) |
| --- | ---: | ---: | ---: | ---: |
| Parse + extract link URLs and text | 466.6 ± 5.1 | +1.0% (+0.3 to +1.7%) | 461.5 ± 4.3 | +2.1% (+0.6 to +3.5%) |
| Parse retaining only links + extract URLs and text | 421.5 ± 3.0 | +0.6% (+0.0 to +1.1%) | 412.1 ± 2.4 | +3.0% (+2.0 to +4.2%) |
| Extract link URLs and text from a parsed tree | 70.2 ± 0.3 | +2.0% (+0.9 to +2.9%) | 67.7 ± 0.4 | +4.1% (+3.3 to +5.1%) |
| Parse and release document | 398.9 ± 4.9 | +1.4% (+0.5 to +2.6%) | 404.1 ± 8.9 | +0.5% (−3.4 to +3.6%) |
| Parse + read page metadata | 414.1 ± 4.5 | +1.1% (+0.0 to +2.3%) | 411.2 ± 4.0 | +1.7% (+0.2 to +3.2%) |
| Parse + extract headings and paragraphs | 526.9 ± 4.8 | +0.7% (−0.1 to +1.4%) | 522.5 ± 4.1 | +1.5% (+0.1 to +3.0%) |
| Count elements by tag on a parsed tree | 187.0 ± 0.7 | +7.0% (+5.7 to +8.5%) | 187.4 ± 0.5 | +7.9% (+7.1 to +8.7%) |

## Pages and correctness

We used the test split of the Web Content Extraction Benchmark, taking 20 pages
each of articles, collections, documentation,
forums, listings, products and services. Within each type we sorted by uncompressed
HTML size and took the midpoint of each twentieth. This gives small and large pages
and weights the seven types equally. The 140 pages cover 135 domains and range from
774 to 316,465 bytes (median 85,019). The runner checks a fingerprint of the 140
sorted page IDs and their uncompressed HTML digests before timing. Downloaded
HTML stays outside this repository.
[WCXB revision `c039d5e`](https://github.com/Murrough-Foley/web-content-extraction-benchmark/tree/c039d5ee9f5a3a984a0e167e63aacd04e76e78a9)

Both wheels produced identical extraction outputs on every page. In particular, full
and partial parsing returned the same 22,104 ordered `(href, descendant text)` pairs.
We also compared these pairs to selectolax 1.0.0 (Lexbor), with exact matches on 137
of 140 pages. Astral preserves source nesting, while Lexbor applies browser-style
HTML recovery. All 140 pages are included in the timings. In the historical run,
all 63 tests passed against each installed wheel on each applicable Python version.

## Measurement

We built the historical release wheels from `4ba2c2f` with the project's locked dependencies,
Rust 1.99.0, PyO3 0.29.3 and maturin 1.15.0. The build settings differed only by
the `pyo3/abi3-py314` feature. We compared the *same* `cp314-abi3` wheel against a
`cp314-cp314` wheel on CPython 3.14.8 and a `cp315-cp315` wheel on CPython 3.15.0.
All were tagged `manylinux_2_34_x86_64` and ran serially on one pinned logical CPU
of a Linux AMD EPYC Milan VM, using ordinary GIL-enabled CPython.

Each workload processes the entire corpus once to warm up, then once under the timer.
End-to-end timings start with in-memory bytes, include UTF-8 decoding and discard the
result inside the timed loop. The two “parsed tree” tasks reuse documents prepared
outside the timer. Link extraction builds a Python list of URL and text pairs.
The metadata task reads title, canonical URL, description and Open Graph image.
The headings and paragraphs task returns a list of tag and text pairs.

Each of 20 pairs uses two fresh Python processes on the same CPU, with the same
shuffled page and workload order. Which wheel runs first alternates between pairs.
We report the geometric mean of paired ABI3/native time ratios and a percentile
bootstrap interval (10,000 resamples of whole pairs, stratified by execution order).
The intervals describe repeatability on these pages and this machine.
[Historical 3.14 pairs](wheel-abi-samples/4ba2c2f-cp314.json) ·
[Historical 3.15 pairs](wheel-abi-samples/4ba2c2f-cp315.json)

To calculate the table from a saved set of observations, run from the
repository root. The summary uses only the Python standard library.

```sh
python -I benchmarks/wheel_abi.py --summarize benchmarks/wheel-abi-samples/4ba2c2f-cp314.json
```

## Reproduce on Linux

Run from the repository root with Rust 1.99.0 and both supported Python
versions available to uv. Start with the October 29 wheel sources and the
benchmark runner in this checkout.

```sh
d=$(mktemp -d)
runner="$PWD/benchmarks/wheel_abi.py"
revision=98a6a38dcc5e3f85e77a11139e38927d511430a4
feature=abi3
git clone https://github.com/Murrough-Foley/web-content-extraction-benchmark "$d/wcxb"
git -C "$d/wcxb" checkout c039d5ee9f5a3a984a0e167e63aacd04e76e78a9
```

For the historical table, select its source tree, wheel feature, and API calls
before building. Skip this block for the October 29 results.

```sh
revision=4ba2c2f671e8b77a30b0ec5d3e0921690db0218f
sed -e 's/retain_subtrees="a"/tags=["a"]/g' -e 's/d\.select("\*")/d.elements()/g' \
    "$runner" > "$d/historical-runner.py"
runner="$d/historical-runner.py"
feature=pyo3/abi3-py314
```

Build the ABI3 wheel once and use that artifact on both interpreters. The
runner loads the extension directly from each unpacked wheel, checks its path,
and verifies the extraction outputs against the pinned corpus baseline before
timing. Pass `--check` in place of `--output` to run only these checks.

```sh
export RUSTUP_TOOLCHAIN=1.99.0
src="$d/source"
mkdir "$src"
git archive "$revision" | tar -x -C "$src"
printf 'maturin==1.15.0\n' > "$d/build-constraints.txt"
args='build-args=--compatibility pypi --auditwheel check'
uv build "$src" --wheel --no-sources --python 3.14.8 --out-dir "$d/wheels" \
    --build-constraints "$d/build-constraints.txt" --config-setting "$args --features $feature"
for py in 3.14.8 3.15.0; do
    uv build "$src" --wheel --no-sources --python "$py" --out-dir "$d/wheels" \
        --build-constraints "$d/build-constraints.txt" --config-setting "$args"
    UV_PROJECT_ENVIRONMENT="$d/env-$py" uv sync --project "$src" --locked \
        --python "$py" --group benchmark --no-install-project
    interpreter="$d/env-$py/bin/python"
    cpu=$("$interpreter" -c 'import os; print(min(os.sched_getaffinity(0)))')
    taskset -c "$cpu" "$interpreter" -I "$runner" \
        "$d/wcxb" "$d/wheels" --output "$d/results-$py.json"
done
```
