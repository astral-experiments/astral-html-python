# /// script
# requires-python = ">=3.12"
# dependencies = ["matplotlib==3.10.7"]
# ///
"""Regenerate filtered-links.png with `uv run --script benchmarks/plot.py`."""

import json
from pathlib import Path

import matplotlib.pyplot as plt  # ty: ignore[unresolved-import]

directory = Path(__file__).parent
data = json.loads((directory / "filtered-links.json").read_text())
sites = {"pypi": "PyPI", "github": "GitHub", "wikipedia": "Wikipedia"}
parsers = [
    ("astral-html", "astral-html-python", "o", "#007563"),
    ("selectolax (Lexbor)", "selectolax", "s", "#46648d"),
    ("lxml", "lxml", "^", "#a65b18"),
    ("Beautiful Soup", "Beautiful Soup", "D", "#71617c"),
]

fig, ax = plt.subplots(figsize=(5.4, 2.6), layout="constrained")
for parser, label, marker, color in parsers:
    rows = [row for row in data["measurements"] if row["parser"] == parser]
    points = ax.errorbar(
        [row["mean_us"] for row in rows],
        [sites[row["fixture"]] for row in rows],
        xerr=[row["stderr_us"] for row in rows],
        fmt=marker,
        color=color,
        markersize=6,
        capsize=4,
    )
    points.lines[0].set_label(label)

ax.set_xscale("log")
ax.set_xticks([10, 100, 1000, 10000, 100000], ["10", "100", "1k", "10k", "100k"])
ax.minorticks_off()
ax.set_ylim(2.45, -0.45)
ax.set_xlabel("Mean scrape time (µs, log scale)", fontsize=12)
ax.tick_params(length=0, labelsize=11, pad=5)
ax.grid(axis="x", color="#dee3e6", linewidth=0.8)
ax.spines[:].set_visible(False)
ax.legend(
    ncols=2,
    loc="lower center",
    bbox_to_anchor=(0.5, 1.02),
    frameon=False,
    fontsize=11,
    handlelength=1.0,
    columnspacing=1.4,
)
fig.savefig(directory / "filtered-links.png", dpi=180)
