"""
visualizer.py
-------------
Creates charts for vineyard grape-variety composition:

  • Pie chart      – one per vineyard (variety breakdown)
  • Stacked bar    – all vineyards side by side (horizontal, easier to read)

Both static (matplotlib/PNG) and interactive (plotly/HTML) versions are
generated.

TTB threshold (≥ 75 %): when a single variety dominates, that variety is
labelled as the "TTB variety" and shown with a distinct annotation.
"""

import json
import logging
import os
import textwrap
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")            # non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.figure import Figure
import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colour palette – enough distinct colours for many varieties
# ---------------------------------------------------------------------------

_PALETTE = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9a6324", "#fffac8", "#800000", "#aaffc3",
    "#808000", "#ffd8b1", "#000075", "#a9a9a9", "#ffffff",
    "#ffe119", "#e6beff", "#fabebe", "#008080", "#4b0082",
    "#7fff00", "#dc143c", "#00ced1", "#ff8c00", "#9400d3",
]

TTB_THRESHOLD = 75.0   # %
_OTHERS_KEY   = "Other"
_UNKNOWN_KEY  = "Unknown %"


# ---------------------------------------------------------------------------
# Colour assignment
# ---------------------------------------------------------------------------

class ColourRegistry:
    """Assigns a consistent colour to each grape variety across all charts."""

    def __init__(self):
        self._map: Dict[str, str] = {
            # Fixed colours for the most common varieties
            "Zinfandel":           "#e6194b",
            "Alicante Bouschet":   "#800000",
            "Petite Sirah":        "#4363d8",
            "Carignan":            "#f58231",
            "Grenache":            "#9a6324",
            "Syrah":               "#911eb4",
            "Mourvèdre":           "#42d4f4",
            "Cinsaut":             "#f032e6",
            "Cabernet Sauvignon":  "#3cb44b",
            "Merlot":              "#469990",
            "Barbera":             "#dcbeff",
            "Sangiovese":          "#fabed4",
            "Chardonnay":          "#ffe119",
            "Palomino":            "#bfef45",
            _OTHERS_KEY:           "#a9a9a9",
            _UNKNOWN_KEY:          "#d3d3d3",
        }
        self._counter = len(self._map)

    def get(self, variety: str) -> str:
        if variety not in self._map:
            self._map[variety] = _PALETTE[self._counter % len(_PALETTE)]
            self._counter += 1
        return self._map[variety]

    def legend_handles(self, varieties: List[str]) -> List[mpatches.Patch]:
        return [
            mpatches.Patch(facecolor=self.get(v), label=v, edgecolor="white")
            for v in varieties
        ]


_REGISTRY = ColourRegistry()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_varieties(varieties_json: str) -> Dict[str, Optional[float]]:
    """Parse the varieties_json column from the analysed DataFrame."""
    if not varieties_json or varieties_json == "{}":
        return {}
    try:
        return json.loads(varieties_json)
    except (json.JSONDecodeError, TypeError):
        return {}


def _collapse_small(
    varieties: Dict[str, Optional[float]],
    threshold: float = 3.0,
) -> Tuple[Dict[str, float], float]:
    """
    Return (known_dict, unknown_total) where:
      • entries with pct < threshold are folded into "Other"
      • entries with pct = None are counted separately (unknown_total)
    """
    known: Dict[str, float] = {}
    other_sum = 0.0
    unknown_sum = 0.0

    for var, pct in varieties.items():
        if pct is None:
            unknown_sum += 0.0          # we don't know the actual %
        elif pct >= threshold:
            known[var] = pct
        else:
            other_sum += pct

    if other_sum > 0:
        known[_OTHERS_KEY] = round(other_sum, 2)

    return known, unknown_sum


def _has_useful_data(varieties: Dict[str, Optional[float]]) -> bool:
    return any(v is not None and v > 0 for v in varieties.values())


# ---------------------------------------------------------------------------
# Single-vineyard pie chart (matplotlib)
# ---------------------------------------------------------------------------

def plot_vineyard_pie(
    name: str,
    varieties_json: str,
    ttb_variety: str = "",
    output_path: Optional[str] = None,
    ax: Optional[plt.Axes] = None,
    min_pct: float = 3.0,
) -> Optional[Figure]:
    """
    Draw a pie chart for one vineyard.

    Parameters
    ----------
    name           : vineyard display name
    varieties_json : JSON string from analyser
    ttb_variety    : dominant variety (>= 75 %) if applicable
    output_path    : save PNG here (if given)
    ax             : draw into this Axes (if given); otherwise create a figure
    min_pct        : varieties below this % are folded into "Other"
    """
    raw = _load_varieties(varieties_json)
    if not raw or not _has_useful_data(raw):
        log.debug("No variety data for %s – skipping pie", name)
        return None

    known, _ = _collapse_small(raw, threshold=min_pct)
    if not known:
        return None

    labels = list(known.keys())
    sizes  = list(known.values())
    colors = [_REGISTRY.get(v) for v in labels]

    # Build wedge explode: pop out TTB variety slightly
    explode = [0.05 if v == ttb_variety else 0 for v in labels]

    standalone = ax is None
    if standalone:
        fig, ax = plt.subplots(figsize=(7, 6))
    else:
        fig = ax.figure

    wedges, texts, autotexts = ax.pie(
        sizes,
        labels=None,
        colors=colors,
        explode=explode,
        autopct=lambda p: f"{p:.1f}%" if p >= min_pct else "",
        startangle=140,
        pctdistance=0.78,
        wedgeprops={"edgecolor": "white", "linewidth": 1.2},
    )
    for at in autotexts:
        at.set_fontsize(8)

    # Title
    ttb_note = f"\n(TTB: {ttb_variety})" if ttb_variety else ""
    wrapped_name = "\n".join(textwrap.wrap(name, width=40))
    ax.set_title(wrapped_name + ttb_note, fontsize=10, fontweight="bold", pad=12)

    # Legend (outside the pie to avoid clutter)
    ax.legend(
        handles=_REGISTRY.legend_handles(labels),
        loc="lower center",
        bbox_to_anchor=(0.5, -0.18),
        ncol=min(3, len(labels)),
        fontsize=7,
        frameon=False,
    )

    if standalone:
        plt.tight_layout()
        if output_path:
            fig.savefig(output_path, dpi=150, bbox_inches="tight")
            log.info("Saved pie chart → %s", output_path)
        return fig

    return fig


# ---------------------------------------------------------------------------
# Multi-vineyard stacked horizontal bar chart (matplotlib)
# ---------------------------------------------------------------------------

def plot_stacked_bar(
    df: pd.DataFrame,
    output_path: Optional[str] = None,
    min_pct: float = 3.0,
    max_vineyards: int = 60,
) -> Optional[Figure]:
    """
    Draw a horizontal stacked bar chart with one bar per vineyard.

    Each bar shows the percentage composition of grape varieties.  Vineyards
    without any variety data are excluded.

    Parameters
    ----------
    df           : analysed DataFrame (from analyser.analyse_all)
    output_path  : save PNG here
    min_pct      : varieties below this % collapsed into "Other"
    max_vineyards: clip to first N vineyards (sorted by name) for readability
    """
    # Build a wide matrix: rows = vineyards, cols = variety names
    rows = []
    vineyard_names = []

    for _, row in df.iterrows():
        raw = _load_varieties(str(row.get("varieties_json", "{}")))
        if not raw or not _has_useful_data(raw):
            continue
        known, _ = _collapse_small(raw, threshold=min_pct)
        if not known:
            continue
        rows.append(known)
        vineyard_names.append(row["name"] or row["url"])

    if not rows:
        log.warning("No variety data available for stacked bar chart.")
        return None

    # Limit for legibility
    if len(rows) > max_vineyards:
        rows = rows[:max_vineyards]
        vineyard_names = vineyard_names[:max_vineyards]

    wide = pd.DataFrame(rows, index=vineyard_names).fillna(0)

    # Order columns by total percentage across all vineyards (most common first)
    col_order = wide.sum(axis=0).sort_values(ascending=False).index.tolist()
    wide = wide[col_order]

    # Figure height scales with number of vineyards
    n = len(wide)
    fig_height = max(8, n * 0.45)
    fig, ax = plt.subplots(figsize=(14, fig_height))

    lefts = [0.0] * n
    bar_height = 0.75

    for col in col_order:
        values = wide[col].tolist()
        color  = _REGISTRY.get(col)
        bars   = ax.barh(
            wide.index,
            values,
            left=lefts,
            color=color,
            height=bar_height,
            edgecolor="white",
            linewidth=0.5,
            label=col,
        )
        # Label bars that are large enough to read
        for bar, val, left in zip(bars, values, lefts):
            if val >= 8:
                ax.text(
                    left + val / 2,
                    bar.get_y() + bar.get_height() / 2,
                    f"{val:.0f}%",
                    ha="center", va="center",
                    fontsize=6.5, color="white", fontweight="bold",
                )
        lefts = [l + v for l, v in zip(lefts, values)]

    ax.set_xlim(0, 100)
    ax.set_xlabel("Percentage (%)", fontsize=11)
    ax.set_title(
        "Historic Vineyard Society – Grape Variety Composition",
        fontsize=13, fontweight="bold", pad=14,
    )
    ax.xaxis.grid(True, linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", labelsize=8)

    # Legend outside the plot
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(
        handles, labels,
        loc="upper left",
        bbox_to_anchor=(1.01, 1),
        fontsize=8,
        frameon=True,
        title="Variety",
        title_fontsize=9,
    )

    plt.tight_layout()

    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        log.info("Saved stacked bar → %s", output_path)

    return fig


# ---------------------------------------------------------------------------
# Grid of pie charts (all vineyards on one figure)
# ---------------------------------------------------------------------------

def plot_all_pies(
    df: pd.DataFrame,
    output_path: Optional[str] = None,
    cols: int = 4,
    min_pct: float = 3.0,
) -> Optional[Figure]:
    """
    Lay out one pie chart per vineyard in a grid.
    Vineyards without variety data are skipped.
    """
    eligible = [
        row for _, row in df.iterrows()
        if _has_useful_data(_load_varieties(str(row.get("varieties_json", "{}"))))
    ]

    if not eligible:
        log.warning("No variety data for pie grid.")
        return None

    rows_count = (len(eligible) + cols - 1) // cols
    fig_w = cols * 5
    fig_h = rows_count * 5.5

    fig, axes = plt.subplots(rows_count, cols, figsize=(fig_w, fig_h))
    axes_flat = axes.flatten() if rows_count > 1 else [axes] if cols == 1 else list(axes)

    for i, row in enumerate(eligible):
        ax = axes_flat[i]
        plot_vineyard_pie(
            name=row.get("name") or row.get("url", f"Vineyard {i+1}"),
            varieties_json=str(row.get("varieties_json", "{}")),
            ttb_variety=str(row.get("ttb_variety", "")),
            ax=ax,
            min_pct=min_pct,
        )

    # Hide unused axes
    for j in range(len(eligible), len(axes_flat)):
        axes_flat[j].set_visible(False)

    fig.suptitle(
        "Historic Vineyard Society – Variety Composition per Vineyard",
        fontsize=14, fontweight="bold", y=1.01,
    )
    plt.tight_layout()

    if output_path:
        fig.savefig(output_path, dpi=130, bbox_inches="tight")
        log.info("Saved pie grid → %s", output_path)

    return fig


# ---------------------------------------------------------------------------
# Interactive Plotly stacked bar
# ---------------------------------------------------------------------------

def plot_interactive_bar(
    df: pd.DataFrame,
    output_path: Optional[str] = None,
    min_pct: float = 3.0,
) -> None:
    """
    Build a Plotly interactive horizontal stacked bar chart and save as HTML.
    """
    try:
        import plotly.graph_objects as go
    except ImportError:
        log.warning("plotly not installed – skipping interactive chart.")
        return

    rows = []
    names = []
    for _, row in df.iterrows():
        raw = _load_varieties(str(row.get("varieties_json", "{}")))
        if not raw or not _has_useful_data(raw):
            continue
        known, _ = _collapse_small(raw, threshold=min_pct)
        if not known:
            continue
        rows.append(known)
        names.append(row.get("name") or row.get("url", "?"))

    if not rows:
        return

    wide = pd.DataFrame(rows, index=names).fillna(0)
    col_order = wide.sum(axis=0).sort_values(ascending=False).index.tolist()
    wide = wide[col_order]

    traces = []
    for col in col_order:
        traces.append(
            go.Bar(
                name=col,
                y=wide.index.tolist(),
                x=wide[col].tolist(),
                orientation="h",
                marker_color=_REGISTRY.get(col),
                text=[f"{v:.1f}%" if v >= min_pct else "" for v in wide[col]],
                textposition="inside",
                insidetextanchor="middle",
                hovertemplate=f"<b>%{{y}}</b><br>{col}: %{{x:.1f}}%<extra></extra>",
            )
        )

    fig = go.Figure(traces)
    fig.update_layout(
        barmode="stack",
        title="Historic Vineyard Society – Grape Variety Composition",
        xaxis_title="Percentage (%)",
        xaxis=dict(range=[0, 100]),
        height=max(500, len(wide) * 28 + 200),
        legend=dict(title="Variety", orientation="v"),
        margin=dict(l=300, r=20, t=60, b=40),
        template="plotly_white",
    )

    if output_path:
        fig.write_html(output_path)
        log.info("Saved interactive bar → %s", output_path)
    else:
        fig.show()


# ---------------------------------------------------------------------------
# Convenience: generate all outputs
# ---------------------------------------------------------------------------

def generate_all_charts(df: pd.DataFrame, output_dir: str = "output") -> None:
    """Save every chart type to *output_dir*."""
    os.makedirs(output_dir, exist_ok=True)

    log.info("Generating pie-chart grid …")
    plot_all_pies(df, output_path=os.path.join(output_dir, "pies_grid.png"))

    log.info("Generating stacked bar chart …")
    plot_stacked_bar(df, output_path=os.path.join(output_dir, "stacked_bar.png"))

    log.info("Generating interactive HTML bar chart …")
    plot_interactive_bar(df, output_path=os.path.join(output_dir, "interactive_bar.html"))

    log.info("All charts saved to %s/", output_dir)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    src = sys.argv[1] if len(sys.argv) > 1 else "data/vineyards_analysed.csv"
    if not os.path.exists(src):
        print(f"Input file not found: {src}")
        sys.exit(1)

    df = pd.read_csv(src)
    generate_all_charts(df)
