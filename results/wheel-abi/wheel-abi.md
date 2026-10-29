# Native and stable-ABI wheel performance

This run compares native CPython wheels with one `cp314-abi3` wheel across seven HTML workloads. All three wheels use parser commit `31a0ab41a83b49af8268dfd254d872a12e73f84a`. Both interpreters ran sequentially in one GitHub Actions job on the same host and CPU. CPython 3.14.9 and 3.15.1 installed the same ABI3 wheel, archive SHA-256 `988f6f771f9e82fc0afee2e51f38588d964be729360a7a0281615c550547a1dd`. Both loaded extensions had SHA-256 `e284dea2eeda261689a2e64a39a496a403882838d34bd1097482aefc9dbbea67`. [Measurement run](https://github.com/astral-experiments/astral-html-python/actions/runs/40936484421)

## Corpus and output checks

The sample uses the test split of [WCXB at c039d5e](https://github.com/Murrough-Foley/web-content-extraction-benchmark/tree/c039d5ee9f5a3a984a0e167e63aacd04e76e78a9). For each of the seven page types, sort records by uncompressed byte length and page ID. Select 20 at the midpoint ranks of 20 equally sized bins. The timed input is a UTF-8 response body already in memory.

Across 140 pages, both wheels on both interpreters returned identical outputs (SHA-256 `775da69bdda49057bd2c1b12254858954dd8783b9cc553bad137e0b932af829d`). Full parsing, retained anchor subtrees and cached tree selection produced the same ordered href/text pairs. The parser returned 22,104 links and matched Lexbor 1.0.0 exactly on 137 pages. Lexbor returned 22,201 links. The artifact contains the differing page IDs, per-page output digests and selected body hashes. The sample manifest SHA-256 is `9a699401e304bfcb16eee1ff5ed451d81eef6c7dac17a11dc12872fd848f01b1`.

## Paired timings

One pair runs each wheel in a fresh process on the same CPU with the same seeded page and workload order. The first wheel alternates across 20 pairs per interpreter. Each job warms the full corpus, collects garbage, then times one full pass. Parse jobs include UTF-8 decoding. Existing-tree jobs use documents parsed before timing. The partial parse retains anchor subtrees with `parse(..., retain_subtrees="a")`. The histogram iterates over `doc.select("*")`.

The native column gives mean elapsed microseconds per page and standard error. The ABI3 change is the geometric mean of the paired ABI3/native ratios, minus one. Positive values mean the ABI3 wheel took longer. The 95% percentile interval uses 10,000 paired bootstrap draws, stratified by which wheel ran first, with seed 42.

### CPython 3.14.9

| Workload | Native (µs/page ± SE) | ABI3 change | 95% interval |
| --- | ---: | ---: | ---: |
| parse | 389.06 ± 4.73 | -0.36% | -2.91% to +1.42% |
| parse + links | 449.03 ± 1.10 | +1.09% | +0.56% to +1.60% |
| partial parse + links | 408.09 ± 0.46 | +1.89% | +0.96% to +3.28% |
| links on parsed tree | 69.11 ± 0.30 | +3.86% | +1.96% to +6.14% |
| parse + metadata | 401.63 ± 5.26 | -0.55% | -2.98% to +1.14% |
| parse + headings and paragraphs | 512.79 ± 1.08 | +1.64% | +0.42% to +3.56% |
| tag histogram on parsed tree | 205.88 ± 0.45 | +4.83% | +3.77% to +5.85% |

### CPython 3.15.1

| Workload | Native (µs/page ± SE) | ABI3 change | 95% interval |
| --- | ---: | ---: | ---: |
| parse | 382.59 ± 0.54 | +0.98% | +0.56% to +1.41% |
| parse + links | 449.21 ± 0.69 | +0.95% | +0.67% to +1.24% |
| partial parse + links | 407.93 ± 0.83 | +1.74% | +1.24% to +2.28% |
| links on parsed tree | 69.37 ± 0.25 | +2.53% | +1.65% to +3.48% |
| parse + metadata | 402.24 ± 4.30 | +0.08% | -2.35% to +2.51% |
| parse + headings and paragraphs | 511.85 ± 0.73 | +1.13% | +0.66% to +1.62% |
| tag histogram on parsed tree | 211.18 ± 0.82 | +4.45% | +3.28% to +5.45% |

## Build provenance

The runner used an AMD EPYC 7763 64-Core Processor and pinned each worker to the first allowed CPU. All wheels used Rust 1.97.0, maturin 1.15.0, uv 0.12.23 and the parser's locked release build. The native wheels used each interpreter's full C API. The stable wheel used CPython 3.14 and Cargo feature `pyo3/abi3-py314`. Full build and host details are in [provenance.txt](provenance.txt).

| Wheel | SHA-256 |
| --- | --- |
| `astral_html_python-0.0.1-cp314-abi3-linux_x86_64.whl` | `988f6f771f9e82fc0afee2e51f38588d964be729360a7a0281615c550547a1dd` |
| `astral_html_python-0.0.1-cp314-cp314-linux_x86_64.whl` | `4f3992c9c7c74525592a83500e5b62b3e164123cb831ff22ae90247a2e7360d8` |
| `astral_html_python-0.0.1-cp315-cp315-linux_x86_64.whl` | `c4f60f8bd726727905aee7df345b16ee82a8e7647d653c899662568b3e22c0a8` |

The parser commit was `31a0ab41a83b49af8268dfd254d872a12e73f84a` and the measurement harness commit was `c1bd575f131f07d069a3709c8352288e0f76fc47`.

## Reproduce

Download the report bundle or use this results directory. From an astral-html-python checkout containing the parser commit, run the script below. It creates temporary build directories and isolated environments, builds the three wheels, and measures all 20 pairs for each interpreter. The default interpreter versions are CPython 3.14.9 and 3.15.1. To provide your own interpreter executables, set `PYTHON_314` and `PYTHON_315`.

```sh
export RUSTUP_TOOLCHAIN=1.97.0
bash /path/to/results/run.sh 31a0ab41a83b49af8268dfd254d872a12e73f84a /tmp/wheel-abi-rerun
```

The script fetches the pinned corpus by default. To reuse a copy, set `WCXB_ARCHIVE` to the absolute path of that revision's tar.gz archive. It needs Rust 1.97.0 and uv 0.12.23 installed. [Driver](run.sh) · [Measurement code](measure.py)

[CPython 3.14 pairs](cp314/paired_ns.json) · [CPython 3.15 pairs](cp315/paired_ns.json) · [3.14 output checks](cp314/validation.json) · [3.15 output checks](cp315/validation.json) · [Sample manifest](cp314/sample.json)
