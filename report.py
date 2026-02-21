"""
report.py
---------
Generates a comprehensive HTML analysis report from vineyard data.

Sections:
  1. Vineyards with percentage data – varieties > 5% only (interactive chart)
  2. Top 10 varieties overall (by vineyard count)
  3. Top 10 varieties by AVA, County, Sub-Appellation
  4. Regions ranked by number of historic vineyards

Usage:
  python report.py
  python report.py --output-dir output/
  python report.py --min-pct 5.0
"""

import argparse
import json
import os
from collections import Counter, defaultdict
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Data loading & merging
# ---------------------------------------------------------------------------

def load_data(output_dir: str = "output") -> List[dict]:
    """Load vineyard_varieties.json and enrich with Sub-Appellation from raw."""
    varieties_path = os.path.join(output_dir, "vineyard_varieties.json")
    raw_path = os.path.join(output_dir, "vineyards_raw.json")

    with open(varieties_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Build url→Sub-Appellation lookup from raw data
    sub_app_map: Dict[str, str] = {}
    if os.path.exists(raw_path):
        with open(raw_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for r in raw:
            key = r.get("url") or r.get("name", "")
            sub_app_map[key] = r.get("Sub-Appellation") or ""

    for v in data:
        key = v.get("url") or v.get("name", "")
        v["Sub-Appellation"] = sub_app_map.get(key, "")

    return data


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def vineyards_with_pct(data: List[dict], min_pct: float = 5.0) -> List[dict]:
    """Vineyards that have pct data; varieties filtered to > min_pct."""
    result = []
    for v in data:
        filtered = sorted(
            [var for var in v["varieties"] if var["pct"] is not None and var["pct"] > min_pct],
            key=lambda x: x["pct"],
            reverse=True,
        )
        if filtered:
            result.append({**v, "varieties_shown": filtered})
    return result


def top_varieties_overall(data: List[dict], top_n: int = 10) -> List[Tuple[str, int]]:
    """Count how many vineyards each variety appears in (all 197)."""
    counter: Counter = Counter()
    for v in data:
        seen = set()
        for var in v["varieties"]:
            name = var["name"]
            if name not in seen:
                counter[name] += 1
                seen.add(name)
    return counter.most_common(top_n)


def top_varieties_by_region(
    data: List[dict], region_key: str, top_n: int = 10
) -> Dict[str, List[Tuple[str, int]]]:
    """For each region value, return the top N varieties by vineyard count."""
    buckets: Dict[str, Counter] = defaultdict(Counter)
    for v in data:
        region = v.get(region_key, "") or ""
        if not region:
            continue
        seen = set()
        for var in v["varieties"]:
            name = var["name"]
            if name not in seen:
                buckets[region][name] += 1
                seen.add(name)
    return {r: c.most_common(top_n) for r, c in sorted(buckets.items())}


def region_vineyard_counts(data: List[dict], region_key: str) -> List[Tuple[str, int]]:
    """Count vineyards per region, sorted descending."""
    counter: Counter = Counter()
    for v in data:
        region = v.get(region_key, "") or ""
        if region:
            counter[region] += 1
    return counter.most_common()


# ---------------------------------------------------------------------------
# HTML building blocks
# ---------------------------------------------------------------------------

_PALETTE = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#469990", "#dcbeff",
    "#9a6324", "#800000", "#aaffc3", "#808000", "#ffd8b1",
    "#000075", "#ffe119", "#fabebe", "#008080", "#4b0082",
]

_FIXED_COLORS = {
    "Zinfandel": "#e6194b",
    "Alicante Bouschet": "#800000",
    "Petite Sirah": "#4363d8",
    "Carignan": "#f58231",
    "Grenache": "#9a6324",
    "Syrah": "#911eb4",
    "Mourvèdre": "#42d4f4",
    "Cinsaut": "#f032e6",
    "Cabernet Sauvignon": "#3cb44b",
    "Merlot": "#469990",
    "Barbera": "#dcbeff",
    "Sangiovese": "#fabed4",
    "Chardonnay": "#ffe119",
    "Palomino": "#bfef45",
    "Mission": "#aaffc3",
}


def _color(variety: str, idx: int = 0) -> str:
    return _FIXED_COLORS.get(variety, _PALETTE[idx % len(_PALETTE)])


def _variety_colors(varieties: List[str]) -> List[str]:
    extra_idx = 0
    colors = []
    for v in varieties:
        if v in _FIXED_COLORS:
            colors.append(_FIXED_COLORS[v])
        else:
            colors.append(_PALETTE[extra_idx % len(_PALETTE)])
            extra_idx += 1
    return colors


def _plotly_pct_chart(vineyards: List[dict]) -> str:
    """Plotly stacked horizontal bar for vineyards with percentage data."""
    all_varieties: List[str] = []
    seen = set()
    for v in vineyards:
        for var in v["varieties_shown"]:
            if var["name"] not in seen:
                all_varieties.append(var["name"])
                seen.add(var["name"])

    colors = _variety_colors(all_varieties)
    names = [v["name"] for v in vineyards]

    traces = []
    for var_name, color in zip(all_varieties, colors):
        xs = []
        for v in vineyards:
            pct = next((x["pct"] for x in v["varieties_shown"] if x["name"] == var_name), 0)
            xs.append(pct)
        traces.append(f"""{{
            type: 'bar',
            name: {json.dumps(var_name)},
            orientation: 'h',
            y: {json.dumps(names)},
            x: {json.dumps(xs)},
            marker: {{color: {json.dumps(color)}}},
            hovertemplate: '<b>%{{y}}</b><br>{var_name}: %{{x:.1f}}%<extra></extra>'
        }}""")

    traces_js = ",\n".join(traces)
    height = max(350, len(vineyards) * 55 + 150)

    return f"""
<div id="pct-chart"></div>
<script>
Plotly.newPlot('pct-chart', [
  {traces_js}
], {{
  barmode: 'stack',
  xaxis: {{title: 'Percentage (%)', range: [0, 100]}},
  yaxis: {{automargin: true}},
  height: {height},
  legend: {{title: {{text: 'Variety'}}}},
  margin: {{l: 220, r: 20, t: 20, b: 50}},
  template: 'plotly_white'
}});
</script>
"""


def _plotly_top_varieties_bar(top: List[Tuple[str, int]], chart_id: str, title: str) -> str:
    """Horizontal bar chart for top varieties by vineyard count."""
    varieties = [t[0] for t in reversed(top)]
    counts = [t[1] for t in reversed(top)]
    colors = _variety_colors(varieties)

    return f"""
<div id="{chart_id}"></div>
<script>
Plotly.newPlot('{chart_id}', [{{
  type: 'bar',
  orientation: 'h',
  y: {json.dumps(varieties)},
  x: {json.dumps(counts)},
  marker: {{color: {json.dumps(colors)}}},
  hovertemplate: '<b>%{{y}}</b><br>Vineyards: %{{x}}<extra></extra>'
}}], {{
  title: {json.dumps(title)},
  xaxis: {{title: 'Number of vineyards', dtick: 1}},
  yaxis: {{automargin: true}},
  height: {max(300, len(top) * 38 + 100)},
  margin: {{l: 200, r: 20, t: 50, b: 50}},
  template: 'plotly_white',
  showlegend: false
}});
</script>
"""


def _region_counts_table(counts: List[Tuple[str, int]], label: str) -> str:
    """Ranked table of regions by vineyard count with an inline bar."""
    max_count = counts[0][1] if counts else 1
    rows = []
    for rank, (region, count) in enumerate(counts, 1):
        bar_width = int(count / max_count * 180)
        rows.append(f"""
        <tr>
          <td class="rank">{rank}</td>
          <td>{region}</td>
          <td class="count-cell">
            <div class="bar-bg">
              <div class="bar-fill" style="width:{bar_width}px"></div>
            </div>
            {count}
          </td>
        </tr>""")
    return f"""
<div class="region-table-wrap">
  <h3>{label}</h3>
  <table class="region-table">
    <thead><tr><th>#</th><th>Region</th><th>Vineyards</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</div>"""


def _top_varieties_region_section(
    by_region: Dict[str, List[Tuple[str, int]]],
    region_label: str,
) -> str:
    """Collapsible accordion of top-10 variety tables per region."""
    blocks = []
    for region, top in by_region.items():
        if not top:
            continue
        max_count = top[0][1]
        rows = []
        for rank, (variety, count) in enumerate(top, 1):
            bar_w = int(count / max_count * 140)
            rows.append(f"""
            <tr>
              <td class="rank">{rank}</td>
              <td>{variety}</td>
              <td class="count-cell">
                <div class="bar-bg">
                  <div class="bar-fill" style="width:{bar_w}px"></div>
                </div>
                {count}
              </td>
            </tr>""")
        safe_id = region.replace(" ", "-").replace("'", "").replace("(", "").replace(")", "")
        blocks.append(f"""
<details class="accordion">
  <summary>{region} <span class="badge">{sum(c for _, c in top)} variety appearances</span></summary>
  <table class="region-table compact">
    <thead><tr><th>#</th><th>Variety</th><th>Vineyards</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</details>""")

    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# Full HTML report
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #f8f6f1;
  color: #2c2c2c;
  line-height: 1.55;
}
header {
  background: #2d4a22;
  color: #fff;
  padding: 2rem 2.5rem 1.5rem;
}
header h1 { font-size: 1.8rem; font-weight: 700; }
header p  { margin-top: .4rem; opacity: .85; font-size: .95rem; }
.stat-row {
  display: flex; gap: 1.5rem; margin-top: 1.2rem; flex-wrap: wrap;
}
.stat-box {
  background: rgba(255,255,255,.15);
  border-radius: 8px;
  padding: .6rem 1.1rem;
  text-align: center;
}
.stat-box .num { font-size: 1.6rem; font-weight: 700; }
.stat-box .lbl { font-size: .75rem; opacity: .8; text-transform: uppercase; letter-spacing: .04em; }

main { max-width: 1100px; margin: 2rem auto; padding: 0 1.5rem 4rem; }

section { background: #fff; border-radius: 10px; padding: 1.8rem 2rem; margin-bottom: 2rem;
          box-shadow: 0 1px 4px rgba(0,0,0,.08); }
section h2 { font-size: 1.25rem; font-weight: 700; color: #2d4a22; margin-bottom: .3rem; }
section .subtitle { font-size: .88rem; color: #666; margin-bottom: 1.2rem; }

.region-tables { display: flex; gap: 1.5rem; flex-wrap: wrap; }
.region-table-wrap { flex: 1; min-width: 260px; }
.region-table-wrap h3 { font-size: 1rem; color: #2d4a22; margin-bottom: .6rem; }

table { width: 100%; border-collapse: collapse; font-size: .88rem; }
th { background: #f0ede6; text-align: left; padding: .45rem .7rem; font-weight: 600; color: #444; }
td { padding: .38rem .7rem; border-bottom: 1px solid #f0ede6; vertical-align: middle; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #faf8f3; }
.rank { color: #999; font-size: .82rem; width: 28px; }
.count-cell { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
.bar-bg { background: #e8e4dc; border-radius: 3px; height: 10px; display: inline-block; width: 180px; }
.bar-fill { background: #4a7c35; border-radius: 3px; height: 10px; display: inline-block; }
table.compact .bar-bg { width: 140px; }

details.accordion {
  border: 1px solid #e8e4dc;
  border-radius: 7px;
  margin-bottom: .6rem;
  overflow: hidden;
}
details.accordion summary {
  cursor: pointer;
  padding: .7rem 1rem;
  font-weight: 600;
  background: #f8f6f1;
  list-style: none;
  display: flex;
  align-items: center;
  gap: .6rem;
  user-select: none;
}
details.accordion summary::-webkit-details-marker { display: none; }
details.accordion summary::before {
  content: '▶';
  font-size: .7rem;
  transition: transform .15s;
  color: #888;
}
details[open].accordion summary::before { transform: rotate(90deg); }
details.accordion table { margin: 0; }
.badge {
  font-size: .74rem;
  font-weight: 400;
  background: #e8e4dc;
  border-radius: 10px;
  padding: .1rem .55rem;
  color: #666;
  margin-left: auto;
}

.note { font-size: .82rem; color: #888; margin-top: .8rem; font-style: italic; }
"""


def build_report(data: List[dict], min_pct: float = 5.0) -> str:
    total = len(data)
    ava_counts = region_vineyard_counts(data, "AVA")
    county_counts = region_vineyard_counts(data, "County")
    sub_counts = region_vineyard_counts(data, "Sub-Appellation")
    with_pct = vineyards_with_pct(data, min_pct)
    top_overall = top_varieties_overall(data, top_n=10)
    top_by_ava = top_varieties_by_region(data, "AVA", top_n=10)
    top_by_county = top_varieties_by_region(data, "County", top_n=10)
    top_by_sub = top_varieties_by_region(data, "Sub-Appellation", top_n=10)

    unique_varieties: set = set()
    for v in data:
        for var in v["varieties"]:
            unique_varieties.add(var["name"])

    # ── Section 1: Vineyards with pct data ──────────────────────────────
    pct_chart = _plotly_pct_chart(with_pct) if with_pct else "<p>No percentage data available.</p>"
    pct_table_rows = []
    for v in with_pct:
        variety_str = ", ".join(
            f"{var['name']} ({var['pct']:.0f}%)" for var in v["varieties_shown"]
        )
        pct_table_rows.append(
            f"<tr><td><b>{v['name']}</b></td><td>{v.get('AVA','')}</td>"
            f"<td>{v.get('County','')}</td><td>{variety_str}</td></tr>"
        )

    # ── Section 2: Top 10 overall ────────────────────────────────────────
    overall_chart = _plotly_top_varieties_bar(
        top_overall, "overall-chart", "Top 10 grape varieties – all historic vineyards"
    )

    # ── Section 3–5: Per-region top varieties (accordions) ───────────────
    ava_section = _top_varieties_region_section(top_by_ava, "AVA")
    county_section = _top_varieties_region_section(top_by_county, "County")
    sub_section = _top_varieties_region_section(top_by_sub, "Sub-Appellation")

    # ── Section 6: Region vineyard counts ────────────────────────────────
    ava_table = _region_counts_table(ava_counts, "By AVA")
    county_table = _region_counts_table(county_counts, "By County")
    sub_table = _region_counts_table(sub_counts, "By Sub-Appellation") if sub_counts else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>California Historic Vineyards – Analysis Report</title>
  <style>{_CSS}</style>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
</head>
<body>

<header>
  <h1>California Historic Vineyards – Analysis Report</h1>
  <p>Data source: Historic Vineyard Society · historicvineyardsociety.org</p>
  <div class="stat-row">
    <div class="stat-box"><div class="num">{total}</div><div class="lbl">Total vineyards</div></div>
    <div class="stat-box"><div class="num">{len(ava_counts)}</div><div class="lbl">AVAs</div></div>
    <div class="stat-box"><div class="num">{len(county_counts)}</div><div class="lbl">Counties</div></div>
    <div class="stat-box"><div class="num">{len(sub_counts)}</div><div class="lbl">Sub-appellations</div></div>
    <div class="stat-box"><div class="num">{len(unique_varieties)}</div><div class="lbl">Grape varieties</div></div>
    <div class="stat-box"><div class="num">{len(with_pct)}</div><div class="lbl">With % data</div></div>
  </div>
</header>

<main>

<!-- ── Section 1 ── -->
<section>
  <h2>Vineyards with percentage data</h2>
  <p class="subtitle">
    {len(with_pct)} of {total} vineyards have explicit variety percentages.
    Only varieties representing more than {min_pct:.0f}% are shown.
  </p>
  {pct_chart}
  <table style="margin-top:1.2rem">
    <thead>
      <tr><th>Vineyard</th><th>AVA</th><th>County</th><th>Varieties (&gt;{min_pct:.0f}%)</th></tr>
    </thead>
    <tbody>{''.join(pct_table_rows)}</tbody>
  </table>
</section>

<!-- ── Section 2 ── -->
<section>
  <h2>Top 10 grape varieties – all vineyards</h2>
  <p class="subtitle">
    Ranked by the number of vineyards in which each variety appears
    (regardless of percentage). Covers all {total} vineyards.
  </p>
  {overall_chart}
</section>

<!-- ── Section 3 ── -->
<section>
  <h2>Top 10 varieties by AVA</h2>
  <p class="subtitle">
    Expand an AVA to see how many of its vineyards contain each variety.
    {len(top_by_ava)} AVAs represented.
  </p>
  {ava_section}
</section>

<!-- ── Section 4 ── -->
<section>
  <h2>Top 10 varieties by County</h2>
  <p class="subtitle">
    {len(top_by_county)} counties represented.
  </p>
  {county_section}
</section>

<!-- ── Section 5 ── -->
<section>
  <h2>Top 10 varieties by Sub-Appellation</h2>
  <p class="subtitle">
    {len(top_by_sub)} sub-appellations represented.
    {'Sub-appellation data available for a subset of vineyards.' if top_by_sub else 'No sub-appellation data available.'}
  </p>
  {sub_section if sub_section else '<p class="note">No sub-appellation data found.</p>'}
</section>

<!-- ── Section 6 ── -->
<section>
  <h2>Regions by number of historic vineyards</h2>
  <p class="subtitle">All regions ranked from most to fewest vineyards.</p>
  <div class="region-tables">
    {ava_table}
    {county_table}
    {sub_table}
  </div>
</section>

</main>
</body>
</html>"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate vineyard analysis HTML report")
    p.add_argument("--output-dir", default="output", metavar="DIR")
    p.add_argument("--min-pct", type=float, default=5.0,
                   help="Minimum %% to show a variety in the percentage section (default: 5.0)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    data = load_data(args.output_dir)
    print(f"Loaded {len(data)} vineyards")

    html = build_report(data, min_pct=args.min_pct)

    out_path = os.path.join(args.output_dir, "report.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Report saved → {out_path}")


if __name__ == "__main__":
    main()
