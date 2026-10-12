"""Estimate retained native + Python RSS per document in fresh Linux processes."""

from __future__ import annotations

import argparse
import ctypes
import gc
import math
import platform
import statistics
import subprocess
import sys
from pathlib import Path

# Python may use safe-path mode, which excludes the script directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from formatting import format_measurement

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FILES = {
    "pypi": "iniconfig.html",
    "github": "github-parse5.html",
    "wikipedia": "wiki-42.html",
}


def rss_kib() -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    raise RuntimeError("VmRSS is unavailable")


def trim() -> None:
    gc.collect()
    libc = ctypes.CDLL(None)
    if not hasattr(libc, "malloc_trim"):
        raise RuntimeError("this experiment requires Linux with glibc malloc_trim")
    libc.malloc_trim(0)


def worker(fixture: str, count: int, mode: str) -> None:
    import astral_html

    source = (FIXTURES / FILES[fixture]).read_bytes().decode("utf-8")
    # Warm up Python and parser one-time allocations before the baseline.
    astral_html.parse(source)
    astral_html.parse(source, tags=["a"])
    trim()
    before = rss_kib()
    if mode == "partial":
        documents = [astral_html.parse(source, tags=["a"]) for _ in range(count)]
    else:
        documents = [astral_html.parse(source) for _ in range(count)]
    trim()
    after = rss_kib()
    # Keep every document alive through the measurement.
    assert len(documents) == count
    print((after - before) / count)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--samples", type=int, default=7, help="fresh-process samples per mode"
    )
    parser.add_argument(
        "--documents", type=int, default=64, help="simultaneously retained documents"
    )
    parser.add_argument("--fixture", choices=FILES, default="wikipedia")
    parser.add_argument("--worker", choices=("full", "partial"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.samples < 2 or args.documents < 1:
        parser.error("--samples must be at least 2 and --documents must be positive")
    if args.worker:
        worker(args.fixture, args.documents, args.worker)
        return
    if sys.platform != "linux":
        parser.error("this experiment requires Linux /proc and glibc")

    results: dict[str, list[float]] = {"full": [], "partial": []}
    # Alternate order so a systematic drift does not always favor one mode.
    for index in range(args.samples):
        modes = ("full", "partial") if index % 2 == 0 else ("partial", "full")
        for mode in modes:
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                mode,
                "--fixture",
                args.fixture,
                "--documents",
                str(args.documents),
            ]
            output = subprocess.check_output(command, text=True)
            results[mode].append(float(output))
            print(
                f"{mode}: sample {index + 1}/{args.samples}",
                file=sys.stderr,
                flush=True,
            )

    print(f"Python {platform.python_version()}")
    print(
        f"Fixture: {args.fixture}; {args.documents} retained documents per fresh process"
    )
    print(f"{args.samples} process samples; mean (SE), KiB/document\n")
    print("| Mode | Resident memory increase (SE), KiB/document |")
    print("| --- | ---: |")
    for mode in ("full", "partial"):
        values = results[mode]
        mean = statistics.mean(values)
        se = statistics.stdev(values) / math.sqrt(len(values))
        print(f"| {mode} | {format_measurement(mean, se)} |")


if __name__ == "__main__":
    main()
