# Wheel ABI timings on CPython 3.15.1

Parser source `31a0ab41a83b49af8268dfd254d872a12e73f84a`. WCXB source `c039d5ee9f5a3a984a0e167e63aacd04e76e78a9`. Output SHA-256 `775da69bdda49057bd2c1b12254858954dd8783b9cc553bad137e0b932af829d`.

140 test-split pages. 22,104 extracted links. 137 pages matched Lexbor 1.0.0 exactly. Both wheel builds gave identical output.

20 fresh-process pairs with alternating run order. The native column gives an arithmetic mean and standard error in µs/page. Change is the geometric mean of paired ABI3/native timing ratios minus one. Positive values mean a slower ABI3 wheel. The 95% interval resamples pairs within each order (10,000 draws, seed 42).

| Workload | Native (µs/page ± SE) | ABI3 change | 95% interval |
| --- | ---: | ---: | ---: |
| parse | 382.59 ± 0.54 | +0.98% | +0.56% to +1.41% |
| parse + links | 449.21 ± 0.69 | +0.95% | +0.67% to +1.24% |
| partial parse + links | 407.93 ± 0.83 | +1.74% | +1.24% to +2.28% |
| links on parsed tree | 69.37 ± 0.25 | +2.53% | +1.65% to +3.48% |
| parse + metadata | 402.24 ± 4.30 | +0.08% | -2.35% to +2.51% |
| parse + headings and paragraphs | 511.85 ± 0.73 | +1.13% | +0.66% to +1.62% |
| tag histogram on parsed tree | 211.18 ± 0.82 | +4.45% | +3.28% to +5.45% |
