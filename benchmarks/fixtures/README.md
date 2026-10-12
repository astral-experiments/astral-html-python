# Fixture sources

These are fixed, complete HTML responses committed with their source licenses,
so benchmark and test results do not depend on a website changing or being
available. They were copied byte-for-byte from `astral-html` revision
[`b363c5e79fb5b896d5ac7b7bd78786fd5e9d196c`](https://github.com/astral-sh/astral-html/tree/b363c5e79fb5b896d5ac7b7bd78786fd5e9d196c).

| File | Description and upstream source | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `iniconfig.html` | Captured PyPI Simple API response for iniconfig, from [astral-tl's benchmark](https://github.com/astral-sh/astral-tl/blob/04bbd94a054e164a3d057160977197ca25194bc5/benches/tl.rs), revision `04bbd94a054e164a3d057160977197ca25194bc5`. | 6,144 | `470b4150301f29038e0eeea63d4a13fba17e4563c32c2005ef71a99c87196b4b` |
| `github-parse5.html` | GitHub repository page, from [parse5](https://github.com/inikulin/parse5/blob/e65eae9a9dc27f1b7eb71868d245ca83070ccc4a/test/data/location-info/github-parse5/data.html), revision `e65eae9a9dc27f1b7eb71868d245ca83070ccc4a`. | 45,233 | `7e19a6a26f9f563988f5aa7a79369c846e18e41cf67ff46c311d012116f1777f` |
| `wiki-42.html` | Wikipedia article page, from [parse5](https://github.com/inikulin/parse5/blob/e65eae9a9dc27f1b7eb71868d245ca83070ccc4a/test/data/location-info/wiki-42/data.html), revision `e65eae9a9dc27f1b7eb71868d245ca83070ccc4a`. | 222,328 | `cbe27182a5f181b37c1548cf7a686e2dbb1c80f2b205f16c33cdeaa6be379085` |

The upstream repository licenses are in `LICENSE-astral-tl` and `LICENSE-parse5`. The captured web pages can also contain third-party content under their own terms. In particular, `wiki-42.html` contains text from Wikipedia contributors' [42 (number), revision 592782173](https://en.wikipedia.org/w/index.php?title=42_(number)&oldid=592782173), which the snapshot identifies as available under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/); its embedded footer has the original notice and attribution links.
