"""Compare Servo and the unchanged lexical parser on captured HTML pages.

Use --corpus PATH for the separate, untracked public corpus. With no corpus,
compare the three committed benchmark fixtures. Timings include parse and,
separately, parse plus link extraction; file reads are outside timed regions.
"""

import argparse
import gc
import hashlib
import json
import math
import platform
import random
import statistics
import time
from functools import partial
from pathlib import Path
from typing import Literal, TypedDict

from astral_html import parse

type Parser = Literal["lexical", "servo"]


class ComparisonRow(TypedDict):
    id: str
    bytes: int
    link_count: dict[Parser, int]
    links_equal: bool
    us: dict[Parser, dict[str, float]]


def sources(corpus: Path | None) -> list[tuple[str, str, int]]:
    if corpus is None:
        pages = sorted((Path(__file__).parent / "fixtures").glob("*.html"))
        entries = [(path.stem, path, None) for path in pages]
    else:
        manifest = json.loads((corpus / "corpus" / "manifest.json").read_text())
        entries = [
            (entry["id"], corpus / ".corpus" / "pages" / entry["file"], entry)
            for entry in manifest["entries"]
        ]

    output = []
    for name, path, entry in entries:
        raw = path.read_bytes()
        if entry is not None:
            assert len(raw) == entry["bytes"], name
            assert hashlib.sha256(raw).hexdigest() == entry["sha256"], name
        output.append((name, raw.decode("utf-8", errors="replace"), len(raw)))
    return output


def links(document) -> list[tuple[str | None, str]]:
    return [(node.get("href"), node.text) for node in document.select("a[href]")]


def parse_links(source: str, parser: Parser) -> list[tuple[str | None, str]]:
    return links(parse(source, parser=parser))


def sample(run, minimum_ms: float) -> float:
    count = 1
    while True:
        start = time.perf_counter_ns()
        for _ in range(count):
            run()
        elapsed = time.perf_counter_ns() - start
        if elapsed >= minimum_ms * 1_000_000:
            return elapsed / count / 1_000
        count *= 2


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "--corpus", type=Path, help="corpus checkout with corpus/manifest.json"
    )
    cli.add_argument("--samples", type=int, default=5)
    cli.add_argument("--min-sample-ms", type=float, default=10)
    cli.add_argument("--reference-lexbor", action="store_true")
    cli.add_argument("--output", type=Path, help="write machine-readable JSON report")
    args = cli.parse_args()
    if (
        args.samples < 2
        or not math.isfinite(args.min_sample_ms)
        or args.min_sample_ms <= 0
    ):
        cli.error("need at least two samples and a positive batch duration")

    pages = sources(args.corpus)
    gc.enable()
    rows: list[ComparisonRow] = []
    failures = []
    reference_mismatches = []
    rng = random.Random(817)
    for name, source, size in pages:
        comparisons: dict[Parser, list[tuple[str | None, str]]] = {}
        errors = {}
        for parser in ("lexical", "servo"):
            try:
                document = parse(source, parser=parser)
                comparisons[parser] = links(document)
            except ValueError as error:
                errors[parser] = str(error)
        if args.reference_lexbor:
            from selectolax.lexbor import LexborHTMLParser

            expected = [
                (node.attrs.get("href"), node.text())
                for node in LexborHTMLParser(source).css("a[href]")
            ]
            for parser, actual in comparisons.items():
                if expected != actual:
                    reference_mismatches.append(
                        {
                            "id": name,
                            "parser": parser,
                            "expected_count": len(expected),
                            "actual_count": len(actual),
                        }
                    )
        if errors:
            failures.append({"id": name, "bytes": size, "errors": errors})
            print(f"{name:32} {size:>8} B  unable to compare: {errors}", flush=True)
            continue
        values = {
            mode: {workload: [] for workload in ("parse", "parse_links")}
            for mode in comparisons
        }
        operations = []
        for parser in comparisons:
            read = partial(parse, source, parser=parser)
            operations.append((parser, "parse", read))
            operations.append(
                (parser, "parse_links", partial(parse_links, source, parser))
            )
        for _ in range(args.samples):
            rng.shuffle(operations)
            for parser, workload, run in operations:
                gc.collect()
                values[parser][workload].append(sample(run, args.min_sample_ms))
        rows.append(
            {
                "id": name,
                "bytes": size,
                "link_count": {
                    parser: len(items) for parser, items in comparisons.items()
                },
                "links_equal": comparisons["servo"] == comparisons["lexical"],
                "us": {
                    parser: {
                        workload: round(statistics.median(samples), 3)
                        for workload, samples in workloads.items()
                    }
                    for parser, workloads in values.items()
                },
            }
        )
        row = rows[-1]
        print(
            f"{row['id']:32} {row['bytes']:>8} B  "
            f"parse {row['us']['lexical']['parse']:>9.1f} / {row['us']['servo']['parse']:>9.1f} µs  "
            f"parse+links {row['us']['lexical']['parse_links']:>9.1f} / "
            f"{row['us']['servo']['parse_links']:>9.1f} µs  "
            f"links equal {row['links_equal']}",
            flush=True,
        )
    total_bytes = sum(size for _, _, size in pages)
    totals = {
        parser: {
            workload: round(sum(row["us"][parser][workload] for row in rows), 3)
            for workload in ("parse", "parse_links")
        }
        for parser in ("lexical", "servo")
    }
    report = {
        "python": platform.python_version(),
        "machine": platform.platform(),
        "samples": args.samples,
        "minimum_sample_ms": args.min_sample_ms,
        "pages": len(pages),
        "total_bytes": total_bytes,
        "compared_pages": len(rows),
        "failures": failures,
        "reference_mismatches": reference_mismatches,
        "link_differences": sum(not row["links_equal"] for row in rows),
        "sum_of_page_medians_us": totals,
        "rows": rows,
    }
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "rows"}, indent=2
        )
    )
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
