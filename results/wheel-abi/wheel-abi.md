# Native and stable-ABI wheel performance

This run compares native CPython wheels with one `cp314-abi3` wheel across seven HTML workloads. All three wheels use parser commit `98a6a38dcc5e3f85e77a11139e38927d511430a4`. CPython 3.14.9 and 3.15.1 ran sequentially on the same runner and CPU. Both installed the same ABI3 wheel (SHA-256 `5ed3f6ffdcf70690c0c38df40f65e5b4d6e90b17f825fc217fd975637bef1703`) and loaded identical extension binaries (SHA-256 `59b25b48816ac119939db8d7f9b467caa54d560247ca9288420215e5c7a13fda`).

This report supersedes the [measurements on 31a0ab4](https://github.com/astral-experiments/astral-html-python/blob/932058f88863ae426ee2522105fc53dd10734363/results/wheel-abi/wheel-abi.md). The newer parser includes changes to UTF-8 conversion and selector work accounting.

## Corpus and output checks

The sample uses the test split of [WCXB at c039d5e](https://github.com/Murrough-Foley/web-content-extraction-benchmark/tree/c039d5ee9f5a3a984a0e167e63aacd04e76e78a9). For each of the seven page types, sort records by uncompressed byte length and page ID. Select 20 at the midpoint ranks of 20 equally sized bins. The timed input is a UTF-8 response body already in memory.

Across 140 pages, both wheels on both interpreters returned identical outputs (SHA-256 `775da69bdda49057bd2c1b12254858954dd8783b9cc553bad137e0b932af829d`). Full parsing, retained anchor subtrees and cached tree selection produced the same ordered href/text pairs. The parser returned 22,104 links and matched Lexbor 1.0.0 exactly on 137 pages. Lexbor returned 22,201 links. The artifact contains the differing page IDs, per-page output digests and selected body hashes. The sample manifest SHA-256 is `9a699401e304bfcb16eee1ff5ed451d81eef6c7dac17a11dc12872fd848f01b1`.

## Paired timings

One pair runs each wheel in a fresh process on the same CPU with the same seeded page and workload order. The first wheel alternates across 20 pairs per interpreter. Each job warms the full corpus, collects garbage, then times one full pass. Parse jobs include UTF-8 decoding. Existing-tree jobs use documents parsed before timing. The partial parse retains anchor subtrees with `parse(..., retain_subtrees="a")`. The histogram iterates over `doc.select("*")`.

The native column gives mean elapsed microseconds per page and standard error. The ABI3 change is the geometric mean of the paired ABI3/native ratios, minus one. Positive values mean the ABI3 wheel took longer. The 95% percentile interval uses 10,000 paired bootstrap draws, stratified by which wheel ran first, with seed 42.

### CPython 3.14.9

| Workload | Native (µs/page ± SE) | ABI3 change | 95% interval |
| --- | ---: | ---: | ---: |
| parse | 388.56 ± 1.90 | -0.95% | -1.80% to -0.09% |
| parse + links | 452.59 ± 1.92 | +1.12% | -0.41% to +3.33% |
| partial parse + links | 418.65 ± 2.50 | -0.82% | -1.88% to +0.25% |
| links on parsed tree | 70.54 ± 1.82 | +1.94% | -3.01% to +6.08% |
| parse + metadata | 400.14 ± 1.64 | -0.50% | -1.52% to +0.75% |
| parse + headings and paragraphs | 525.69 ± 6.96 | -1.79% | -4.34% to +0.04% |
| tag histogram on parsed tree | 208.41 ± 0.85 | +5.47% | +4.36% to +6.90% |

### CPython 3.15.1

| Workload | Native (µs/page ± SE) | ABI3 change | 95% interval |
| --- | ---: | ---: | ---: |
| parse | 383.57 ± 1.35 | -0.60% | -1.46% to +0.25% |
| parse + links | 451.77 ± 3.30 | -0.82% | -2.30% to +0.23% |
| partial parse + links | 412.56 ± 1.19 | -0.88% | -1.46% to -0.33% |
| links on parsed tree | 68.97 ± 0.49 | +3.26% | +2.03% to +4.52% |
| parse + metadata | 393.72 ± 0.47 | -0.20% | -0.50% to +0.10% |
| parse + headings and paragraphs | 512.39 ± 1.17 | +0.46% | -0.83% to +2.18% |
| tag histogram on parsed tree | 216.84 ± 0.52 | +2.58% | +1.62% to +3.69% |

## Build provenance

The runner used an AMD EPYC 7763 64-Core Processor and pinned each worker to the first allowed CPU. All wheels used Rust 1.97.0, maturin 1.15.0, uv 0.12.23 and the parser's locked release build. The native wheels used each interpreter's full C API. The stable wheel used CPython 3.14 and the package's `abi3` feature (`pyo3/abi3-py314`). Full build and host details are in [provenance.txt](provenance.txt).

| Wheel | SHA-256 |
| --- | --- |
| `astral_html_python-0.0.1-cp314-abi3-linux_x86_64.whl` | `5ed3f6ffdcf70690c0c38df40f65e5b4d6e90b17f825fc217fd975637bef1703` |
| `astral_html_python-0.0.1-cp314-cp314-linux_x86_64.whl` | `cb39174bd906be303eed3b382e1531215a07a18d5c5a04f3b2a614dea42f410f` |
| `astral_html_python-0.0.1-cp315-cp315-linux_x86_64.whl` | `f222743e58ef4f9a42e3c567c752d45ae9b6c3351c60c4f9dc1ce8063ce90af2` |

The parser commit was `98a6a38dcc5e3f85e77a11139e38927d511430a4` and the measurement harness commit was `a2b7aaef74e6349666569b85279c3312d664019b`.

## Reproduce

Download the report bundle or use this results directory. From an astral-html-python checkout containing the parser commit, run the script below. It creates temporary build directories and isolated environments, builds the three wheels, and measures all 20 pairs for each interpreter. The default interpreter versions are CPython 3.14.9 and 3.15.1. To provide your own interpreter executables, set `PYTHON_314` and `PYTHON_315`.

```sh
export RUSTUP_TOOLCHAIN=1.97.0
bash /path/to/results/run.sh 98a6a38dcc5e3f85e77a11139e38927d511430a4 /tmp/wheel-abi-rerun
```

The script fetches the pinned corpus by default. To reuse a copy, set `WCXB_ARCHIVE` to the absolute path of that revision's tar.gz archive. It needs Rust 1.97.0 and uv 0.12.23 installed. [Driver](run.sh) · [Measurement code](measure.py)

[CPython 3.14 pairs](cp314/paired_ns.json) · [CPython 3.15 pairs](cp315/paired_ns.json) · [3.14 output checks](cp314/validation.json) · [3.15 output checks](cp315/validation.json) · [Sample manifest](cp314/sample.json)
