# Benchmarks

Run the benchmark from the repository root:

```console
uv run --group benchmark python benchmarks/run.py
```

Use `--fixture pypi`, `--fixture github`, or `--fixture wikipedia` to select a
page. `--samples` sets the number of fresh process samples (default 20), and
`--min-sample-ms` sets the minimum time per batch (default 20 ms).

The fixtures are a PyPI Simple index, a GitHub repository page, and a Wikipedia
article. See [fixture sources](fixtures/README.md) for provenance and licenses.
Before timing, the runner checks each parser's ordered `(href, text)` results
against Lexbor's and checks partial parsing against the full parse.

Each library receives the same Python `str`. Timings include creating the
output, but exclude reading the input file. Garbage collection remains enabled
and runs before each batch. Trees involved in reference cycles may be collected
outside the timed batch. Each sample starts a fresh process, checks the outputs,
and measures every workload once in a shuffled order. Each measurement has
three warmup operations followed by a calibrated batch.

The workloads are:

- **Parse**: construct and drop a complete document.
- **Parse + links**: parse and extract URLs and text for every `a[href]`.
- **Parse + filtered CSS**: parse and extract links from a scoped selector:
  PyPI downloads with Python requirements, GitHub repository files, or links
  in Wikipedia article paragraphs.
- **Filtered CSS on existing tree**: run the same filtered query and extract
  its output against an already parsed document. The libraries use their normal
  selector APIs, which differ in whether they cache parsed selectors.
- **Partial parse + links**: for astral-html only, parse with `tags=["a"]` and
  extract `a[href]`. This tests the opt-in retained-subtree mode with the same
  output as the full parse and link extraction.

Parsers differ in how they build trees and handle malformed HTML. Agreement is
checked only for these fixtures and queries.

## Results

These results use Python 3.14.8, a release build of astral-html-python 0.1.0,
selectolax 1.0.0, lxml 6.1.3, cssselect 1.5.0, and Beautiful Soup 4.15.0. Each
cell is the mean and standard error (SE) in microseconds per operation over 20
process samples. The SE covers variation among those samples, though longer-term
changes in conditions can cause additional variation.
Means are rounded to at most three significant digits and no finer than the SE;
SEs are rounded to one significant digit.

| Workload | Parser | PyPI (µs) | GitHub (µs) | Wikipedia (µs) |
| --- | --- | ---: | ---: | ---: |
| Parse | astral-html | 7.74 (SE 0.04) | 220 (SE 10) | 1,600 (SE 200) |
| Parse | selectolax (Lexbor) | 62 (SE 2) | 850 (SE 30) | 3,000 (SE 300) |
| Parse | lxml | 56.9 (SE 0.3) | 1,000 (SE 8) | 4,740 (SE 20) |
| Parse | Beautiful Soup (lxml) | 730 (SE 20) | 11,500 (SE 80) | 62,900 (SE 500) |
| Parse + links | astral-html | 14.5 (SE 0.1) | 290 (SE 20) | 2,500 (SE 200) |
| Parse + links | selectolax (Lexbor) | 170 (SE 10) | 1,010 (SE 40) | 3,900 (SE 300) |
| Parse + links | lxml | 163 (SE 0.5) | 1,420 (SE 20) | 9,180 (SE 40) |
| Parse + links | Beautiful Soup (lxml) | 930 (SE 70) | 12,600 (SE 100) | 72,500 (SE 500) |
| Parse + filtered CSS | astral-html | 12.9 (SE 0.3) | 310 (SE 20) | 2,200 (SE 200) |
| Parse + filtered CSS | selectolax (Lexbor) | 170 (SE 10) | 950 (SE 30) | 3,600 (SE 400) |
| Parse + filtered CSS | lxml | 161 (SE 1) | 1,260 (SE 10) | 6,230 (SE 40) |
| Parse + filtered CSS | Beautiful Soup (lxml) | 900 (SE 30) | 13,300 (SE 60) | 90,500 (SE 800) |
| Filtered CSS on existing tree | astral-html | 4.13 (SE 0.03) | 21.1 (SE 0.3) | 362 (SE 2) |
| Filtered CSS on existing tree | selectolax (Lexbor) | 8.6 (SE 0.1) | 27.7 (SE 0.4) | 225 (SE 4) |
| Filtered CSS on existing tree | lxml | 78 (SE 1) | 168 (SE 1) | 1,350 (SE 40) |
| Filtered CSS on existing tree | Beautiful Soup (lxml) | 116 (SE 0.9) | 1,860 (SE 20) | 27,200 (SE 200) |
| Partial parse + links | astral-html | 18.8 (SE 0.2) | 266 (SE 2) | 2,120 (SE 80) |

Partial parsing was slower on PyPI in this run. The experiment below measures
its effect on retained memory.

## Retained-memory experiment

On Linux with glibc, run:

```console
uv run --group benchmark python benchmarks/memory.py --fixture wikipedia
uv run --group benchmark python benchmarks/memory.py --fixture github
```

Each sample uses a fresh process and measures the RSS increase after retaining
64 parsed documents. This includes native allocations and allocator effects,
but excludes the input string and extracted Python elements. The script
collects garbage and calls `malloc_trim` before each RSS measurement; full and
partial (`tags=["a"]`) samples alternate in order. RSS is an estimate of
retained memory, not a peak-memory measurement.

The mean (SE) over seven samples per mode was:

| Fixture | Full parse (KiB/document) | Partial parse (KiB/document) |
| --- | ---: | ---: |
| GitHub | 294 (SE 0) | 108 (SE 0) |
| Wikipedia | 1,660 (SE 0) | 959 (SE 0) |

All seven samples gave the same RSS-derived values at the reported resolution;
an SE of zero does not mean the measurement is exact.
