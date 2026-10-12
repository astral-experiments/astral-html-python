"""Checks for rounding reported measurements without overstating precision."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "benchmark_formatting",
    Path(__file__).resolve().parents[1] / "benchmarks" / "formatting.py",
)
assert spec is not None and spec.loader is not None
formatting = importlib.util.module_from_spec(spec)
spec.loader.exec_module(formatting)


@pytest.mark.parametrize(
    ("mean", "se", "expected"),
    [
        (14.07, 0.11, "14.1 (SE 0.1)"),
        (1044.42, 1.35, "1,040 (SE 1)"),
        (1507.8, 16.77, "1,510 (SE 20)"),
        (7.54, 0.0004, "7.54 (SE 0.0004)"),
        (1664.06, 0, "1,660 (SE 0)"),
        (50.5, 9.6, "50 (SE 10)"),
        (9.999, 0.001, "10.0 (SE 0.001)"),
        (0.9999, 0.00001, "1.00 (SE 0.00001)"),
    ],
)
def test_measurement_formatting(mean: float, se: float, expected: str) -> None:
    assert formatting.format_measurement(mean, se) == expected
