# Wheel ABI timings on CPython 3.14.9

Parser source `31a0ab41a83b49af8268dfd254d872a12e73f84a`. WCXB source `c039d5ee9f5a3a984a0e167e63aacd04e76e78a9`. Output SHA-256 `775da69bdda49057bd2c1b12254858954dd8783b9cc553bad137e0b932af829d`.

140 test-split pages. 22,104 extracted links. 137 pages matched Lexbor 1.0.0 exactly. Both wheel builds gave identical output.

20 fresh-process pairs with alternating run order. The native column gives an arithmetic mean and standard error in µs/page. Change is the geometric mean of paired ABI3/native timing ratios minus one. Positive values mean a slower ABI3 wheel. The 95% interval resamples pairs within each order (10,000 draws, seed 42).

| Workload | Native (µs/page ± SE) | ABI3 change | 95% interval |
| --- | ---: | ---: | ---: |
| parse | 389.06 ± 4.73 | -0.36% | -2.91% to +1.42% |
| parse + links | 449.03 ± 1.10 | +1.09% | +0.56% to +1.60% |
| partial parse + links | 408.09 ± 0.46 | +1.89% | +0.96% to +3.28% |
| links on parsed tree | 69.11 ± 0.30 | +3.86% | +1.96% to +6.14% |
| parse + metadata | 401.63 ± 5.26 | -0.55% | -2.98% to +1.14% |
| parse + headings and paragraphs | 512.79 ± 1.08 | +1.64% | +0.42% to +3.56% |
| tag histogram on parsed tree | 205.88 ± 0.45 | +4.83% | +3.77% to +5.85% |
