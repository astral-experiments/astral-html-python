# Wheel ABI timings on CPython 3.14.9

Parser source `98a6a38dcc5e3f85e77a11139e38927d511430a4`. WCXB source `c039d5ee9f5a3a984a0e167e63aacd04e76e78a9`. Output SHA-256 `775da69bdda49057bd2c1b12254858954dd8783b9cc553bad137e0b932af829d`.

140 test-split pages. 22,104 extracted links. 137 pages matched Lexbor 1.0.0 exactly. Both wheel builds gave identical output.

20 fresh-process pairs with alternating run order. The native column gives an arithmetic mean and standard error in µs/page. Change is the geometric mean of paired ABI3/native timing ratios minus one. Positive values mean a slower ABI3 wheel. The 95% interval resamples pairs within each order (10,000 draws, seed 42).

| Workload | Native (µs/page ± SE) | ABI3 change | 95% interval |
| --- | ---: | ---: | ---: |
| parse | 388.56 ± 1.90 | -0.95% | -1.80% to -0.09% |
| parse + links | 452.59 ± 1.92 | +1.12% | -0.41% to +3.33% |
| partial parse + links | 418.65 ± 2.50 | -0.82% | -1.88% to +0.25% |
| links on parsed tree | 70.54 ± 1.82 | +1.94% | -3.01% to +6.08% |
| parse + metadata | 400.14 ± 1.64 | -0.50% | -1.52% to +0.75% |
| parse + headings and paragraphs | 525.69 ± 6.96 | -1.79% | -4.34% to +0.04% |
| tag histogram on parsed tree | 208.41 ± 0.85 | +5.47% | +4.36% to +6.90% |
