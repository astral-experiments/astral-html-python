# /// script
# requires-python = ">=3.12"
# dependencies = ["matplotlib==3.10.7"]
# ///
"""Redraw the README charts with `uv run --script benchmarks/plot.py`."""

import json
from pathlib import Path

import matplotlib.pyplot as plt  # ty: ignore[unresolved-import]
from matplotlib import ticker  # ty: ignore[unresolved-import]

directory = Path(__file__).parent
data = json.loads((directory / "filtered-links.json").read_text())
rows = {(row["fixture"], row["parser"]): row for row in data["measurements"]}
sites = {"wikipedia": "Wikipedia", "pypi": "PyPI", "github": "GitHub"}
parsers = {
    "astral-html": "astral-html",
    "selectolax (Lexbor)": "selectolax",
    "lxml": "lxml",
    "Beautiful Soup": "Beautiful Soup",
}

for filename, ink, purple, grid, background in [
    ("filtered-links.png", "#29272e", "#6340ac", "#dedce2", "white"),
    ("filtered-links-dark.png", "#f0eff5", "#ae91eb", "#38363e", "#0d1117"),
]:
    fig, axes = plt.subplots(
        3, 1, sharey=True, figsize=(6.3, 3.9), layout="constrained"
    )
    fig.get_layout_engine().set(h_pad=0.04, hspace=0.07)
    for ax, (fixture, title) in zip(axes, sites.items(), strict=True):
        formatter = ticker.EngFormatter(sep="")
        for index, (parser, label) in enumerate(parsers.items()):
            row = rows[fixture, parser]
            mean, se = row["mean_us"], row["stderr_us"]
            bars = ax.barh(
                label,
                mean,
                height=0.5,
                color=purple,
                xerr=se,
                error_kw={
                    "ecolor": ink,
                    "elinewidth": 1,
                    "capsize": 2.4,
                    "capthick": 0.85,
                },
            )
            if index < 2:
                ax.bar_label(
                    bars,
                    labels=[formatter.format_eng(mean)],
                    padding=3,
                    fontsize=9.5,
                    color=ink,
                )

        # Scale each page separately so the fastest fixtures remain readable
        # alongside Wikipedia. Bars within a page share a zero baseline.
        ticks = ticker.MaxNLocator(
            nbins=2, steps=[1, 2, 2.5, 4, 5, 6, 7.5, 10]
        ).tick_values(0, ax.dataLim.xmax)
        ax.set_xticks(ticks)
        ax.set_xlim(0, ticks[-1] * 1.01)
        ax.xaxis.set_major_formatter(formatter)
        ax.set_ylim(len(parsers) - 0.45, -0.55)
        ax.set_title(title, loc="left", fontsize=12, pad=3, color=ink)
        ax.tick_params(length=0, labelsize=11, colors=ink, pad=4)
        ax.tick_params(axis="x", labelsize=9)
        ax.get_yticklabels()[0].set_fontweight("bold")
        ax.set_axisbelow(True)
        ax.grid(axis="x", color=grid, linewidth=0.8)
        ax.spines[:].set_visible(False)
        ax.set_facecolor(background)

    fig.supxlabel("Time per scrape (µs) · smaller is better", fontsize=11, color=ink)
    fig.savefig(directory / filename, facecolor=background, dpi=180)
    plt.close(fig)
