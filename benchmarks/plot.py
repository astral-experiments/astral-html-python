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
pages = {
    "pypi": "PyPI package index",
    "github": "GitHub file listing",
    "wikipedia": "Wikipedia article",
}
names = {"astral-html": "astral-html-python", "Beautiful Soup": "Beautiful Soup (lxml)"}
ink, accent, grid = "#253545", "#036b60", "#dde3e7"
fig, ax = plt.subplots(figsize=(8.6, 5.6), facecolor="white")
fig.subplots_adjust(left=0.24, right=0.77, top=0.86, bottom=0.13)
fig.text(
    0.035, 0.94, "Time to scrape matching links", fontsize=20, weight="bold", color=ink
)
fig.text(
    0.035,
    0.89,
    "Response bytes → parse HTML → select links with CSS → Python (href, text) pairs",
    fontsize=11,
    color=ink,
)
fig.text(
    0.035,
    0.025,
    "Mean ± 1 standard error across 12 worker processes per page · CPython 3.14.8",
    fontsize=9,
    color=ink,
)

ax.set_xscale("log")
ax.set_xlim(9, 145000)
ax.set_xticks(
    [10, 100, 1000, 10000, 100000], ["10", "100", "1,000", "10,000", "100,000"]
)
ax.minorticks_off()
ax.set_axisbelow(True)
ax.grid(axis="x", color=grid)
ax.set_yticks([])
ax.spines[:].set_visible(False)
ax.tick_params(axis="x", length=0, labelcolor=ink)
ax.set_xlabel(
    "Microseconds per scrape · log scale · lower is faster", color=ink, labelpad=8
)

# Rows share a time axis. Print the intervals too, since some are narrower than a marker.
row = 0
for page, title in pages.items():
    ax.text(
        -0.38,
        row,
        f"{title}  ·  {data['fixtures'][page]['matches']} links",
        transform=ax.get_yaxis_transform(),
        va="center",
        weight="bold",
        color=ink,
    )
    if row == 0:
        ax.text(
            1.03,
            row,
            "Mean ± SE (µs)",
            transform=ax.get_yaxis_transform(),
            va="center",
            weight="bold",
            color=ink,
        )
    for result in data["measurements"]:
        if result["fixture"] != page:
            continue
        row += 1
        mean, se = result["mean_us"], result["stderr_us"]
        parser = result["parser"]
        primary = parser == "astral-html"
        color = accent if primary else ink
        ax.text(
            -0.025,
            row,
            names.get(parser, parser),
            transform=ax.get_yaxis_transform(),
            ha="right",
            va="center",
            fontsize=10,
            color=color,
        )
        ax.errorbar(
            mean,
            row,
            xerr=se,
            fmt="D" if primary else "o",
            color=color,
            markersize=3.5,
            capsize=3.5,
            elinewidth=1.5,
        )
        ax.text(
            1.03,
            row,
            f"{mean:,} ± {se:,}",
            transform=ax.get_yaxis_transform(),
            va="center",
            fontsize=10,
            color=color,
        )
    row += 1.55
ax.set_ylim(row - 1, -0.55)
fig.savefig(directory / "filtered-links.png", dpi=170)
