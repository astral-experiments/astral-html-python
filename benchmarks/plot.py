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
sites = {"pypi": "PyPI", "github": "GitHub", "wikipedia": "Wikipedia"}
parsers = {
    "astral-html": "astral-html-python",
    "selectolax (Lexbor)": "selectolax",
    "lxml": "lxml",
    "Beautiful Soup": "Beautiful Soup",
}

for filename, ink, purple, grid, background in [
    ("filtered-links.png", "#29272e", "#6340ac", "#dedce2", "white"),
    ("filtered-links-dark.png", "#f0eff5", "#ae91eb", "#38363e", "#0d1117"),
]:
    fig, axes = plt.subplots(
        1, 3, sharey=True, figsize=(6.4, 2.05), layout="constrained"
    )
    fig.get_layout_engine().set(wspace=0.12)
    for ax, (fixture, title) in zip(axes, sites.items(), strict=True):
        for parser, label in parsers.items():
            row = rows[fixture, parser]
            mean, se = row["mean_us"], row["stderr_us"]
            rate = 1_000_000 / mean
            low, high = 1_000_000 / (mean + se), 1_000_000 / (mean - se)
            ax.barh(
                label,
                rate,
                height=0.52,
                color=purple,
                xerr=[[rate - low], [high - rate]],
                error_kw={"ecolor": ink, "elinewidth": 1, "capsize": 3, "capthick": 1},
            )

        ticks = ticker.MaxNLocator(nbins=2, steps=[1, 2, 2.5, 4, 5, 10]).tick_values(
            0, ax.dataLim.xmax
        )
        ax.set_xticks(ticks)
        ax.set_xlim(0, ticks[-1])
        ax.xaxis.set_major_formatter(ticker.EngFormatter(sep=""))
        ax.set_ylim(len(parsers) - 0.45, -0.55)
        ax.set_title(title, fontsize=13, color=ink)
        ax.tick_params(length=0, labelsize=11, colors=ink, pad=4)
        ax.set_axisbelow(True)
        ax.grid(axis="x", color=grid, linewidth=0.8)
        ax.spines[:].set_visible(False)
        ax.set_facecolor(background)

    axes[0].get_yticklabels()[0].set_fontweight("bold")
    fig.supxlabel("Scrapes per second", fontsize=12, color=ink)
    fig.savefig(directory / filename, facecolor=background, dpi=180)
    plt.close(fig)
