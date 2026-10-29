# Wheel ABI timings on CPython 3.15.1

Parser source `98a6a38dcc5e3f85e77a11139e38927d511430a4`. WCXB source `c039d5ee9f5a3a984a0e167e63aacd04e76e78a9`. Output SHA-256 `775da69bdda49057bd2c1b12254858954dd8783b9cc553bad137e0b932af829d`.

140 test-split pages. 22,104 extracted links. 137 pages matched Lexbor 1.0.0 exactly. Both wheel builds gave identical output.

20 fresh-process pairs with alternating run order. The native column gives an arithmetic mean and standard error in µs/page. Change is the geometric mean of paired ABI3/native timing ratios minus one. Positive values mean a slower ABI3 wheel. The 95% interval resamples pairs within each order (10,000 draws, seed 42).

| Workload | Native (µs/page ± SE) | ABI3 change | 95% interval |
| --- | ---: | ---: | ---: |
| parse | 383.57 ± 1.35 | -0.60% | -1.46% to +0.25% |
| parse + links | 451.77 ± 3.30 | -0.82% | -2.30% to +0.23% |
| partial parse + links | 412.56 ± 1.19 | -0.88% | -1.46% to -0.33% |
| links on parsed tree | 68.97 ± 0.49 | +3.26% | +2.03% to +4.52% |
| parse + metadata | 393.72 ± 0.47 | -0.20% | -0.50% to +0.10% |
| parse + headings and paragraphs | 512.39 ± 1.17 | +0.46% | -0.83% to +2.18% |
| tag histogram on parsed tree | 216.84 ± 0.52 | +2.58% | +1.62% to +3.69% |
