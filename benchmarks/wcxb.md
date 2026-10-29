# Scraping links across 1,867 HTML pages

This benchmark reads a saved UTF-8 response body, selects `a[href]`, and
builds a Python list of `(href, descendant text)` pairs. It uses the same
parser APIs as the three fixed snapshots. Astral's elapsed time includes
UTF-8 decoding. Its partial-tree mode retains only `a` subtrees. Lexbor,
lxml, and Beautiful Soup receive bytes directly. [Fixed-snapshot benchmarks](README.md)

## Corpus

Murrough Foley's Web Content Extraction Benchmark (WCXB) contains 2,008 HTML
snapshots across its development and test splits. Removing byte-identical
bodies leaves 1,867 pages totaling 427.1 MiB. The smallest is 774 bytes, the
median is 117,686 bytes, and the largest is 5,318,214 bytes. The source URLs
identify 1,613 hostnames. Five distinct bodies have no hostname in their
annotations. [WCXB revision `c039d5e`](https://github.com/Murrough-Foley/web-content-extraction-benchmark/tree/c039d5ee9f5a3a984a0e167e63aacd04e76e78a9) · [Dataset license](https://github.com/Murrough-Foley/web-content-extraction-benchmark/blob/c039d5ee9f5a3a984a0e167e63aacd04e76e78a9/LICENSE)

Each body uses the page-type annotation from its first path in `dev`, then
`test`, in filename order.

| Article | Service | Forum | Listing | Documentation | Collection | Product |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 970 | 221 | 163 | 136 | 130 | 126 | 121 |

Articles account for 52% of the distinct bodies. Each timed page receives
equal weight. The runner checks the SHA-256 fingerprint of the sorted body
digests before using the corpus. [Benchmark runner](run.py)

## Output agreement

Before timing, the runner compares every ordered list against Lexbor's,
including whitespace and duplicate links. Link totals cover each parser's
successful pages. The two Astral modes must agree with each other on every
page, including which inputs they can parse.

The check also compares each parser's results with its pinned SHA-256 digest.
In sorted body-digest order, it hashes the 32-byte body digest followed by the
ordered link pairs as compact ASCII JSON. A rejected page contributes `null`,
and a successful page with no links contributes `[]`. This pins the membership
of both timing groups as well as the extracted URLs and text.

| Parser | Pages matching Lexbor (of 1,867) | Rejected pages | Extracted links |
| --- | ---: | ---: | ---: |
| astral-html-python | 1,757 | 1 | 323,196 |
| selectolax (Lexbor) | 1,867 | 0 | 323,120 |
| lxml | 1,698 | 0 | 323,344 |
| Beautiful Soup (lxml) | 641 | 0 | 323,458 |
| astral-html-python, link subtrees | 1,757 | 1 | 323,196 |

Both Astral modes rejected `dev/html/2875.html.gz` at the nesting limit.
[Parser limits](../docs/parsing.md#resource-limits)

## Time per page

We time all 1,866 pages that every parser completed and separately report the
617 pages where every parser returned the same ordered pairs. Those 617 pages
contribute the same measurements to both columns.

| Parser | All 1,866 pages (µs/page ± SE) | Identical output on 617 pages (µs/page ± SE) |
| --- | ---: | ---: |
| astral-html-python | 792.7 ± 4.9 | 789.6 ± 7.9 |
| selectolax (Lexbor) | 995.9 ± 10.2 | 934.7 ± 22.5 |
| lxml | 2,943.6 ± 9.1 | 2,663.5 ± 17.4 |
| Beautiful Soup (lxml) | 24,391.7 ± 66.1 | 20,096.9 ± 93.0 |
| astral-html-python, link subtrees | 739.8 ± 7.3 | 754.9 ± 19.3 |

On the 617 pages with identical output, Astral's full-tree scrape took
15.2% less time per page than Lexbor on average. The 95% confidence
interval for that reduction was 11.0% to 19.3%, using paired worker timings
and Student's t distribution. [Raw process timings](wcxb-samples.csv)

Times are mean microseconds per page ± one standard error across ten fresh
worker processes. Each worker shuffles pages within the identical-output and
differing-output groups. All parsers see the same page order in that worker.
Parser order rotates across workers, and the groups alternate which runs
first. Each parser warms up on the first five pages in each group. The worker
collects garbage before timing each group and leaves cyclic GC enabled while
scraping. Archive reads, decompression, output comparison, and warmup are
outside the timer.

We measured a native astral-html-python 0.1.0 release wheel built from the
source distribution with Rust 1.99.0 and maturin 1.15.0. The run used
CPython 3.14.8 on a Linux x86-64 AMD EPYC Milan VM with glibc 2.39, pinned
to logical CPU 8. The other libraries were selectolax 1.0.0, lxml 6.1.3,
cssselect 1.5.0, and Beautiful Soup 4.15.0 with the lxml backend.
[Parser revision `bfb4136`](https://github.com/astral-experiments/astral-html-python/tree/bfb41367a78cf1ad76ed5e583b78770acd58689e)

## Reproduce

From the repository root, install a release wheel and the locked benchmark
dependencies. [Build and installation commands](README.md#reproduce)

```sh
data=$(mktemp -d)
revision=c039d5ee9f5a3a984a0e167e63aacd04e76e78a9
curl -fL "https://codeload.github.com/Murrough-Foley/web-content-extraction-benchmark/tar.gz/$revision" \
    -o "$data/wcxb.tar.gz"
cpu=$(.venv/bin/python -c 'import os; print(min(os.sched_getaffinity(0)))')
taskset -c "$cpu" .venv/bin/python -I benchmarks/run.py --wcxb "$data/wcxb.tar.gz" --samples 10
```

On systems without Linux CPU affinity, omit the `cpu` assignment and
`taskset -c "$cpu"`. Pass `--check` to run only the corpus and output checks.
The timing run prints each worker's measurements before the summary.

For an intentional parser or dependency change, run `--check` on the pinned
archive with the locked dependencies. A mismatch reports the observed digests.
Compare the old and new ordered pairs and rejections on the affected parser
before updating `WCXB_OUTPUT_DIGESTS` in the runner. Refresh the agreement
table and timings when the outputs or comparison groups change.
