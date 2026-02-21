"""
build_report.py
---------------
Generates output/index.html – a polished, interactive analytics page
styled after historicvineyardsociety.org.
"""

import csv, json, collections, re

# ── Load data ──────────────────────────────────────────────────────────────
rows_csv = list(csv.DictReader(open("output/vineyards_analysed.csv")))
raw_json = json.load(open("output/vineyard_varieties.json"))

# Build master vineyard list (use raw_json as primary – has richer pct data)
vineyards = []
for item in raw_json:
    varieties_list = item.get("varieties", [])
    var_names = [v["name"] for v in varieties_list if v.get("name")]
    var_pct   = {v["name"]: v["pct"] for v in varieties_list
                 if v.get("name") and v.get("pct") is not None}
    vineyards.append({
        "n": item["name"],
        "d": item.get("Decade", ""),
        "c": item.get("County", ""),
        "a": item.get("AVA", ""),
        "v": var_names,       # list of variety names
        "pct": var_pct,       # {variety: pct} for those with data
    })

# ── Aggregations ───────────────────────────────────────────────────────────
DECADES_ORDERED = ["All","1860s","1870s","1880s","1890s","1900s",
                   "1910s","1920s","1930s","1940s","1950s","1960s","1970s"]

# Top 15 varieties overall (for color assignment)
all_var_ctr = collections.Counter()
for vy in vineyards:
    for v in vy["v"]:
        all_var_ctr[v] += 1
TOP_VARIETIES = [v for v, _ in all_var_ctr.most_common(15)]

# Top 15 counties / AVAs by vineyard count
county_ctr = collections.Counter(vy["c"] for vy in vineyards if vy["c"])
ava_ctr    = collections.Counter(vy["a"] for vy in vineyards if vy["a"])
TOP_COUNTIES = [c for c, _ in county_ctr.most_common(15)]
TOP_AVAS     = [a for a, _ in ava_ctr.most_common(15)]

# Decade timeline (vineyard count per decade)
dec_timeline = {d: 0 for d in DECADES_ORDERED[1:]}
for vy in vineyards:
    if vy["d"] in dec_timeline:
        dec_timeline[vy["d"]] += 1

# Key stats
n_total    = len(vineyards)
n_avas     = len(set(vy["a"] for vy in vineyards if vy["a"]))
n_counties = len(set(vy["c"] for vy in vineyards if vy["c"]))
n_varieties= len(all_var_ctr)
n_pct      = sum(1 for vy in vineyards if vy["pct"])

# Vineyards with pct data (> 5 % threshold, for Sec 1 stacked bar)
PCT_VINEYARDS = []
for vy in vineyards:
    pcts = {k: v for k, v in vy["pct"].items() if v >= 5}
    if pcts:
        PCT_VINEYARDS.append({
            "name": vy["n"], "ava": vy["a"], "county": vy["c"],
            "decade": vy["d"], "varieties": pcts
        })

# ── Color palette (15 varieties + Other) ──────────────────────────────────
PALETTE = [
    "#c0392b","#8e44ad","#2471a3","#76448a","#e67e22",
    "#b7950b","#117a65","#512e5f","#0b5345","#784212",
    "#1a5276","#6e2f1a","#7d6608","#4a235a","#196f3d",
    "#7f8c8d",
]
VAR_COLOR = {v: PALETTE[i % len(PALETTE)] for i, v in enumerate(TOP_VARIETIES)}
VAR_COLOR["Other"] = "#aab7b8"

# ── Helpers ────────────────────────────────────────────────────────────────
def filter_by_decade(decade):
    if decade == "All":
        return vineyards
    return [vy for vy in vineyards if vy["d"] == decade]

def variety_counts(subset):
    ctr = collections.Counter()
    for vy in subset:
        for v in vy["v"]:
            ctr[v] += 1
    return ctr

def stacked_data(subset, region_key, top_regions, top_vars):
    """Returns {variety: [count_per_region]} for Plotly stacked bar."""
    # region_key: 'c' or 'a'
    region_data = {r: collections.Counter() for r in top_regions}
    for vy in subset:
        r = vy[region_key]
        if r in region_data:
            for v in vy["v"]:
                region_data[r][v] += 1
    result = {}
    for v in top_vars:
        result[v] = [region_data[r][v] for r in top_regions]
    # Other
    result["Other"] = []
    for r in top_regions:
        other = sum(cnt for var, cnt in region_data[r].items() if var not in top_vars)
        result["Other"].append(other)
    return result

# ── Pre-compute data for all decades (embed in JS) ─────────────────────────
per_decade = {}
for dec in DECADES_ORDERED:
    sub = filter_by_decade(dec)
    vc  = variety_counts(sub)
    # top-10 variety bar
    top10 = vc.most_common(10)
    var_bar = {"vars": [v for v,_ in top10], "counts": [c for _,c in top10]}
    # county stacked
    cs = stacked_data(sub, "c", TOP_COUNTIES, TOP_VARIETIES)
    # ava stacked
    av = stacked_data(sub, "a", TOP_AVAS, TOP_VARIETIES)
    per_decade[dec] = {
        "n_vineyards": len(sub),
        "var_bar": var_bar,
        "county": cs,
        "ava": av,
    }

# ── Section 1: pct stacked bar traces ─────────────────────────────────────
pct_vineyard_names = [p["name"] for p in PCT_VINEYARDS]
# Build traces for varieties that appear
pct_var_set = set()
for p in PCT_VINEYARDS:
    pct_var_set.update(p["varieties"].keys())
pct_traces = []
for v in sorted(pct_var_set):
    xs = [p["varieties"].get(v, 0) for p in PCT_VINEYARDS]
    color = VAR_COLOR.get(v, VAR_COLOR["Other"])
    pct_traces.append({
        "type": "bar", "name": v, "orientation": "h",
        "y": pct_vineyard_names, "x": xs,
        "marker": {"color": color},
        "hovertemplate": f"<b>%{{y}}</b><br>{v}: %{{x:.1f}}%<extra></extra>"
    })

# ── Build JS data blobs ────────────────────────────────────────────────────
js_per_decade   = json.dumps(per_decade)
js_top_varieties= json.dumps(TOP_VARIETIES)
js_top_counties = json.dumps(TOP_COUNTIES)
js_top_avas     = json.dumps(TOP_AVAS)
js_var_color    = json.dumps(VAR_COLOR)
js_dec_timeline = json.dumps(dec_timeline)
js_pct_traces   = json.dumps(pct_traces)
js_pct_names    = json.dumps(pct_vineyard_names)
js_dec_ordered  = json.dumps(DECADES_ORDERED)
js_all_var_ctr  = json.dumps({v: c for v, c in all_var_ctr.most_common(10)})

# Overall top10 for static chart
ov_top10 = all_var_ctr.most_common(10)
js_ov_vars   = json.dumps([v for v,_ in reversed(ov_top10)])
js_ov_counts = json.dumps([c for _,c in reversed(ov_top10)])
js_ov_colors = json.dumps([VAR_COLOR.get(v, VAR_COLOR["Other"]) for v,_ in reversed(ov_top10)])

# ── HTML Template ──────────────────────────────────────────────────────────
HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>California Historic Vineyards – Interactive Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600;700&family=Source+Sans+3:wght@300;400;600&display=swap" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
/* ── Reset & base ─────────────────────────────── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

:root {{
  --green-dark:  #1e3d18;
  --green-mid:   #2d5a20;
  --green-light: #4a7c35;
  --gold:        #b8923a;
  --gold-light:  #d4a84b;
  --cream:       #f4efe4;
  --parchment:   #ede5d0;
  --text:        #2a1f14;
  --text-muted:  #6b5d4f;
  --white:       #ffffff;
  --border:      #d8ccb8;
  --card-shadow: 0 2px 12px rgba(30,61,24,.10);
  --radius:      10px;
}}

html {{ scroll-behavior: smooth; }}

body {{
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  background: var(--cream);
  color: var(--text);
  line-height: 1.6;
  font-size: 15px;
}}

/* ── Header ───────────────────────────────────── */
header {{
  background: var(--green-dark);
  color: var(--white);
  padding: 0;
  border-bottom: 4px solid var(--gold);
}}
.header-inner {{
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem 2rem 1.6rem;
  display: flex;
  align-items: center;
  gap: 2rem;
}}
.logo-wrap {{
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: .4rem;
}}
.logo-wrap svg {{ width: 72px; height: 72px; }}
.logo-text {{
  font-family: 'Playfair Display', Georgia, serif;
  font-size: .68rem;
  letter-spacing: .15em;
  text-transform: uppercase;
  color: var(--gold-light);
  text-align: center;
  line-height: 1.3;
}}
.header-copy h1 {{
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 1.9rem;
  font-weight: 700;
  letter-spacing: .01em;
  line-height: 1.2;
}}
.header-copy .tagline {{
  font-size: .9rem;
  opacity: .75;
  margin-top: .35rem;
  font-weight: 300;
}}
.stat-row {{
  display: flex;
  gap: 1.1rem;
  margin-top: 1.3rem;
  flex-wrap: wrap;
}}
.stat-box {{
  background: rgba(255,255,255,.1);
  border: 1px solid rgba(255,255,255,.15);
  border-radius: 7px;
  padding: .55rem 1rem;
  text-align: center;
  min-width: 80px;
}}
.stat-box .num {{
  font-family: 'Playfair Display', serif;
  font-size: 1.55rem;
  font-weight: 700;
  color: var(--gold-light);
  display: block;
}}
.stat-box .lbl {{
  font-size: .7rem;
  opacity: .75;
  text-transform: uppercase;
  letter-spacing: .06em;
  display: block;
}}

/* ── Sticky nav ──────────────────────────────── */
nav.sticky-nav {{
  background: var(--green-mid);
  position: sticky;
  top: 0;
  z-index: 100;
  border-bottom: 2px solid var(--gold);
}}
nav.sticky-nav ul {{
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 1.5rem;
  display: flex;
  gap: 0;
  list-style: none;
  overflow-x: auto;
}}
nav.sticky-nav a {{
  display: block;
  padding: .75rem 1.1rem;
  color: rgba(255,255,255,.8);
  text-decoration: none;
  font-size: .82rem;
  letter-spacing: .04em;
  text-transform: uppercase;
  white-space: nowrap;
  transition: color .15s, border-bottom .15s;
  border-bottom: 2px solid transparent;
}}
nav.sticky-nav a:hover {{
  color: var(--gold-light);
  border-bottom: 2px solid var(--gold-light);
}}

/* ── Main layout ─────────────────────────────── */
main {{
  max-width: 1200px;
  margin: 2.5rem auto;
  padding: 0 1.5rem 5rem;
  display: flex;
  flex-direction: column;
  gap: 2rem;
}}

/* ── Section card ────────────────────────────── */
section.card {{
  background: var(--white);
  border-radius: var(--radius);
  box-shadow: var(--card-shadow);
  border: 1px solid var(--border);
  overflow: hidden;
}}
.card-header {{
  background: var(--green-dark);
  padding: 1rem 1.6rem;
  display: flex;
  align-items: center;
  gap: .8rem;
}}
.card-header h2 {{
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 1.15rem;
  font-weight: 600;
  color: var(--white);
  flex: 1;
}}
.card-header .section-icon {{
  font-size: 1.2rem;
  opacity: .8;
}}
.card-body {{
  padding: 1.5rem 1.6rem;
}}
.subtitle {{
  font-size: .87rem;
  color: var(--text-muted);
  margin-bottom: 1.2rem;
  font-style: italic;
}}

/* ── Ornamental divider ──────────────────────── */
.ornament {{
  text-align: center;
  color: var(--gold);
  letter-spacing: .5em;
  font-size: .9rem;
  margin: .4rem 0 1.2rem;
  user-select: none;
}}

/* ── Decade slider control ───────────────────── */
.slider-wrap {{
  background: var(--parchment);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1.1rem 1.5rem 1rem;
  margin-bottom: 1.4rem;
}}
.slider-wrap label {{
  font-size: .8rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--text-muted);
  display: block;
  margin-bottom: .5rem;
}}
.slider-label-row {{
  display: flex;
  justify-content: space-between;
  font-size: .72rem;
  color: var(--text-muted);
  margin-top: .35rem;
  user-select: none;
}}
.decade-display {{
  font-family: 'Playfair Display', serif;
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--green-dark);
  text-align: center;
  margin-bottom: .5rem;
}}
.decade-display small {{
  font-family: 'Source Sans 3', sans-serif;
  font-size: .8rem;
  color: var(--text-muted);
  font-weight: 400;
  margin-left: .4rem;
}}

input[type=range] {{
  -webkit-appearance: none;
  width: 100%;
  height: 5px;
  background: linear-gradient(to right, var(--green-mid) 0%, var(--green-mid) 0%, var(--border) 0%);
  border-radius: 3px;
  outline: none;
  cursor: pointer;
}}
input[type=range]::-webkit-slider-thumb {{
  -webkit-appearance: none;
  width: 20px; height: 20px;
  background: var(--green-dark);
  border: 3px solid var(--gold);
  border-radius: 50%;
  cursor: pointer;
  box-shadow: 0 1px 4px rgba(0,0,0,.25);
}}
input[type=range]::-moz-range-thumb {{
  width: 20px; height: 20px;
  background: var(--green-dark);
  border: 3px solid var(--gold);
  border-radius: 50%;
  cursor: pointer;
}}

/* ── Two-column grid for county/AVA ─────────── */
.two-col {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.5rem;
}}
@media (max-width: 900px) {{
  .two-col {{ grid-template-columns: 1fr; }}
  .header-inner {{ flex-direction: column; text-align: center; }}
}}

/* ── Accordion (region tables) ───────────────── */
details.accordion {{
  border: 1px solid var(--border);
  border-radius: 7px;
  margin-bottom: .5rem;
  overflow: hidden;
}}
details.accordion summary {{
  cursor: pointer;
  padding: .65rem 1rem;
  font-weight: 600;
  font-size: .9rem;
  background: var(--parchment);
  list-style: none;
  display: flex;
  align-items: center;
  gap: .6rem;
  user-select: none;
}}
details.accordion summary::-webkit-details-marker {{ display: none; }}
details.accordion summary::before {{
  content: '▶';
  font-size: .65rem;
  transition: transform .15s;
  color: var(--gold);
}}
details[open].accordion summary::before {{ transform: rotate(90deg); }}
.badge {{
  font-size: .72rem;
  background: var(--green-dark);
  color: var(--gold-light);
  border-radius: 10px;
  padding: .1rem .55rem;
  margin-left: auto;
  font-weight: 400;
}}

/* ── Tables ──────────────────────────────────── */
table {{
  width: 100%;
  border-collapse: collapse;
  font-size: .86rem;
}}
th {{
  background: var(--parchment);
  text-align: left;
  padding: .45rem .7rem;
  font-weight: 600;
  color: var(--text-muted);
  border-bottom: 2px solid var(--border);
  font-size: .8rem;
  text-transform: uppercase;
  letter-spacing: .04em;
}}
td {{
  padding: .38rem .7rem;
  border-bottom: 1px solid #f0ede6;
  vertical-align: middle;
}}
tr:last-child td {{ border-bottom: none; }}
tr:hover td {{ background: #faf6ee; }}
.rank {{ color: var(--gold); font-size: .8rem; width: 28px; font-weight: 700; }}
.bar-bg {{
  background: var(--parchment);
  border-radius: 3px;
  height: 9px;
  display: inline-block;
  width: 120px;
  vertical-align: middle;
}}
.bar-fill {{
  background: var(--green-mid);
  border-radius: 3px;
  height: 9px;
  display: inline-block;
}}
.count-cell {{
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}}

/* ── Notes & footer ──────────────────────────── */
.note {{
  font-size: .78rem;
  color: var(--text-muted);
  margin-top: .9rem;
  font-style: italic;
}}
footer {{
  background: var(--green-dark);
  color: rgba(255,255,255,.6);
  text-align: center;
  padding: 1.5rem;
  font-size: .82rem;
  border-top: 3px solid var(--gold);
}}
footer a {{ color: var(--gold-light); text-decoration: none; }}

/* ── Summary image grid ──────────────────────── */
.img-grid {{
  display: grid;
  grid-template-columns: 1fr;
  gap: 1rem;
}}
.img-grid img {{
  width: 100%;
  border-radius: 6px;
  border: 1px solid var(--border);
}}
</style>
</head>
<body>

<!-- ══ HEADER ══════════════════════════════════════════════════════════ -->
<header>
  <div class="header-inner">
    <div class="logo-wrap">
      <!-- Grapevine SVG logo inspired by HVS aesthetic -->
      <svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" aria-label="Historic Vineyard Society">
        <circle cx="50" cy="50" r="48" fill="none" stroke="#b8923a" stroke-width="2"/>
        <!-- Vine trunk -->
        <path d="M50 82 Q50 60 50 40" stroke="#d4a84b" stroke-width="2.5" fill="none" stroke-linecap="round"/>
        <!-- Left branch -->
        <path d="M50 62 Q38 56 30 50" stroke="#d4a84b" stroke-width="1.8" fill="none" stroke-linecap="round"/>
        <!-- Right branch -->
        <path d="M50 54 Q62 48 70 44" stroke="#d4a84b" stroke-width="1.8" fill="none" stroke-linecap="round"/>
        <!-- Left leaf -->
        <path d="M30 50 Q22 40 28 34 Q36 38 30 50Z" fill="#4a7c35" opacity=".85"/>
        <!-- Right leaf -->
        <path d="M70 44 Q78 34 72 28 Q64 32 70 44Z" fill="#4a7c35" opacity=".85"/>
        <!-- Top leaf -->
        <path d="M50 40 Q44 30 50 24 Q56 30 50 40Z" fill="#4a7c35" opacity=".85"/>
        <!-- Grapes left cluster -->
        <circle cx="26" cy="58" r="4.5" fill="#c0392b" opacity=".8"/>
        <circle cx="34" cy="62" r="4.5" fill="#9b2335" opacity=".8"/>
        <circle cx="22" cy="64" r="4"   fill="#a52a2a" opacity=".8"/>
        <circle cx="30" cy="68" r="4"   fill="#c0392b" opacity=".8"/>
        <!-- Grapes right cluster -->
        <circle cx="74" cy="52" r="4.5" fill="#c0392b" opacity=".8"/>
        <circle cx="82" cy="56" r="4.5" fill="#9b2335" opacity=".8"/>
        <circle cx="70" cy="59" r="4"   fill="#a52a2a" opacity=".8"/>
        <circle cx="78" cy="63" r="4"   fill="#c0392b" opacity=".8"/>
        <!-- Years text -->
        <text x="50" y="95" text-anchor="middle" font-family="Georgia,serif"
              font-size="7" fill="#b8923a" letter-spacing="1">CALIFORNIA</text>
      </svg>
      <div class="logo-text">Historic<br>Vineyard Society</div>
    </div>
    <div class="header-copy">
      <h1>California Historic Vineyards</h1>
      <p class="tagline">Data source: <a href="https://historicvineyardsociety.org" style="color:var(--gold-light)">historicvineyardsociety.org</a> &nbsp;·&nbsp; {n_total} vineyards catalogued</p>
      <div class="stat-row">
        <div class="stat-box"><span class="num">{n_total}</span><span class="lbl">Vineyards</span></div>
        <div class="stat-box"><span class="num">{n_avas}</span><span class="lbl">AVAs</span></div>
        <div class="stat-box"><span class="num">{n_counties}</span><span class="lbl">Counties</span></div>
        <div class="stat-box"><span class="num">{n_varieties}</span><span class="lbl">Varieties</span></div>
        <div class="stat-box"><span class="num">{n_pct}</span><span class="lbl">With % data</span></div>
      </div>
    </div>
  </div>
</header>

<!-- ══ STICKY NAV ═══════════════════════════════════════════════════════ -->
<nav class="sticky-nav">
  <ul>
    <li><a href="#sec-timeline">Planting Timeline</a></li>
    <li><a href="#sec-decade">By Decade</a></li>
    <li><a href="#sec-county">By County</a></li>
    <li><a href="#sec-ava">By AVA</a></li>
    <li><a href="#sec-pct">Variety %</a></li>
    <li><a href="#sec-overall">Overall</a></li>
    <li><a href="#sec-tables">Region Tables</a></li>
  </ul>
</nav>

<main>

<!-- ══ SHARED DECADE SLIDER (controls sec-decade, sec-county, sec-ava) ═ -->
<section class="card" style="border-color:var(--gold)">
  <div class="card-header" style="background:var(--green-mid)">
    <span class="section-icon">🗓</span>
    <h2>Filter by Decade Planted</h2>
  </div>
  <div class="card-body">
    <div class="slider-wrap">
      <label for="decade-slider">Select a decade – charts below update automatically</label>
      <div class="decade-display" id="decade-display">
        All Decades <small id="vy-count"></small>
      </div>
      <input type="range" id="decade-slider" min="0" max="12" value="0" step="1">
      <div class="slider-label-row">
        <span>All</span><span>1860s</span><span>1870s</span><span>1880s</span><span>1890s</span>
        <span>1900s</span><span>1910s</span><span>1920s</span><span>1930s</span><span>1940s</span>
        <span>1950s</span><span>1960s</span><span>1970s</span>
      </div>
    </div>
    <p class="note">
      Drag the slider to filter the three charts below (Variety, County, and AVA)
      to a specific planting decade. "All" shows data for all 197 vineyards.
    </p>
  </div>
</section>

<!-- ══ SEC 1: PLANTING TIMELINE ════════════════════════════════════════ -->
<section class="card" id="sec-timeline">
  <div class="card-header">
    <span class="section-icon">📅</span>
    <h2>Planting Timeline – Vineyards per Decade</h2>
  </div>
  <div class="card-body">
    <p class="subtitle">Number of vineyards planted in each decade, across all 197 catalogued sites.</p>
    <div class="ornament">❧ ✦ ❧</div>
    <div id="timeline-chart"></div>
  </div>
</section>

<!-- ══ SEC 2: VARIETY BY DECADE ════════════════════════════════════════ -->
<section class="card" id="sec-decade">
  <div class="card-header">
    <span class="section-icon">🍇</span>
    <h2>Variety Distribution — filtered by decade</h2>
  </div>
  <div class="card-body">
    <p class="subtitle">
      Top grape varieties by number of vineyards containing them.
      Use the slider above to filter by planting decade.
    </p>
    <div class="ornament">❧ ✦ ❧</div>
    <div id="variety-chart"></div>
  </div>
</section>

<!-- ══ SEC 3 & 4: COUNTY + AVA STACKED BARS ════════════════════════════ -->
<div class="two-col">

  <section class="card" id="sec-county">
    <div class="card-header">
      <span class="section-icon">🗺</span>
      <h2>County Breakdown</h2>
    </div>
    <div class="card-body">
      <p class="subtitle">
        Top 15 counties. Bars stacked by variety — each segment = number of
        vineyards in that county containing that variety. Bar height exceeds
        vineyard count where multiple varieties coexist.
      </p>
      <div id="county-chart"></div>
    </div>
  </section>

  <section class="card" id="sec-ava">
    <div class="card-header">
      <span class="section-icon">📍</span>
      <h2>AVA Breakdown</h2>
    </div>
    <div class="card-body">
      <p class="subtitle">
        Top 15 AVAs. Same stacking convention as County chart — segments
        show variety appearances, not unique vineyards.
      </p>
      <div id="ava-chart"></div>
    </div>
  </section>

</div>

<!-- ══ SEC 5: VARIETY % ══════════════════════════════════════════════════ -->
<section class="card" id="sec-pct">
  <div class="card-header">
    <span class="section-icon">📊</span>
    <h2>Variety Composition — Vineyards with Percentage Data</h2>
  </div>
  <div class="card-body">
    <p class="subtitle">
      {n_pct} vineyards have explicit variety percentages. Only varieties ≥ 5 % are shown.
    </p>
    <div class="ornament">❧ ✦ ❧</div>
    <div id="pct-chart"></div>
    <table style="margin-top:1.4rem; font-size:.84rem">
      <thead>
        <tr><th>Vineyard</th><th>AVA</th><th>County</th><th>Decade</th><th>Varieties (≥5%)</th></tr>
      </thead>
      <tbody>
"""

for p in PCT_VINEYARDS:
    var_str = ", ".join(f"{v} ({round(pct)}%)" for v, pct in sorted(p["varieties"].items(), key=lambda x: -x[1]))
    HTML += f"""        <tr>
          <td><b>{p['name']}</b></td>
          <td>{p['ava']}</td>
          <td>{p['county']}</td>
          <td>{p['decade']}</td>
          <td>{var_str}</td>
        </tr>
"""

HTML += """      </tbody>
    </table>
  </div>
</section>

<!-- ══ SEC 6: OVERALL TOP 10 ════════════════════════════════════════════ -->
<section class="card" id="sec-overall">
  <div class="card-header">
    <span class="section-icon">🏆</span>
    <h2>Top 10 Grape Varieties — All 197 Vineyards</h2>
  </div>
  <div class="card-body">
    <p class="subtitle">Ranked by number of vineyards containing each variety, regardless of percentage.</p>
    <div class="ornament">❧ ✦ ❧</div>
    <div id="overall-chart"></div>
  </div>
</section>

<!-- ══ SEC 7: REGION TABLES (accordion) ════════════════════════════════ -->
<section class="card" id="sec-tables">
  <div class="card-header">
    <span class="section-icon">📋</span>
    <h2>Top Varieties by AVA — Detailed Tables</h2>
  </div>
  <div class="card-body">
    <p class="subtitle">Expand an AVA to see how many of its vineyards contain each variety.</p>
"""

# Build accordion tables from data
ava_variety_data = collections.defaultdict(lambda: collections.Counter())
for vy in vineyards:
    if vy["a"]:
        for v in vy["v"]:
            ava_variety_data[vy["a"]][v] += 1

for ava_name in sorted(ava_variety_data.keys()):
    vc = ava_variety_data[ava_name]
    total = sum(vc.values())
    top10 = vc.most_common(10)
    max_count = top10[0][1] if top10 else 1
    HTML += f"""
    <details class="accordion">
      <summary>{ava_name} <span class="badge">{total} variety appearances</span></summary>
      <table>
        <thead><tr><th>#</th><th>Variety</th><th>Vineyards</th></tr></thead>
        <tbody>
"""
    for rank, (var, count) in enumerate(top10, 1):
        bar_w = int((count / max_count) * 120)
        HTML += f"""          <tr>
            <td class="rank">{rank}</td>
            <td>{var}</td>
            <td class="count-cell">
              <div class="bar-bg"><div class="bar-fill" style="width:{bar_w}px"></div></div>
              {count}
            </td>
          </tr>
"""
    HTML += """        </tbody>
      </table>
    </details>
"""

HTML += f"""  </div>
</section>

</main>

<footer>
  <p>Data sourced from <a href="https://historicvineyardsociety.org">Historic Vineyard Society</a> · California Historic Vineyard Analysis · Built with Plotly.js</p>
</footer>

<!-- ══ JAVASCRIPT ════════════════════════════════════════════════════════ -->
<script>
// ── Embedded data ─────────────────────────────────────────────────────
const PER_DECADE    = {js_per_decade};
const TOP_VARIETIES = {js_top_varieties};
const TOP_COUNTIES  = {js_top_counties};
const TOP_AVAS      = {js_top_avas};
const VAR_COLOR     = {js_var_color};
const DEC_TIMELINE  = {js_dec_timeline};
const PCT_TRACES    = {js_pct_traces};
const PCT_NAMES     = {js_pct_names};
const DECADES       = {js_dec_ordered};

// ── Color helper ──────────────────────────────────────────────────────
function varColor(v) {{ return VAR_COLOR[v] || VAR_COLOR['Other']; }}

// ── Common Plotly config ──────────────────────────────────────────────
const PLY_CFG = {{responsive: true, displayModeBar: false}};

// ── Timeline chart (static) ───────────────────────────────────────────
Plotly.newPlot('timeline-chart', [{{
  type: 'bar',
  x: Object.keys(DEC_TIMELINE),
  y: Object.values(DEC_TIMELINE),
  marker: {{
    color: Object.values(DEC_TIMELINE).map((_, i) =>
      `hsl(${{200 - i * 12}}, 45%, ${{35 + i * 2}}%)`),
    line: {{color: '#b8923a', width: 1}}
  }},
  hovertemplate: '<b>%{{x}}</b><br>%{{y}} vineyards<extra></extra>'
}}], {{
  xaxis: {{title: 'Decade planted', tickangle: -30}},
  yaxis: {{title: 'Number of vineyards', dtick: 5}},
  height: 340,
  margin: {{l: 60, r: 20, t: 20, b: 60}},
  plot_bgcolor: '#faf9f5',
  paper_bgcolor: '#ffffff',
  font: {{family: 'Source Sans 3, sans-serif', color: '#2a1f14'}},
  hoverlabel: {{bgcolor: '#1e3d18', font: {{color: '#fff'}}}}
}}, PLY_CFG);

// ── Variety bar chart ─────────────────────────────────────────────────
function buildVarietyChart(decade) {{
  const d = PER_DECADE[decade];
  const vars   = d.var_bar.vars;
  const counts = d.var_bar.counts;
  // Sort ascending for horizontal bar (Plotly shows bottom-to-top)
  const pairs = vars.map((v,i) => [v, counts[i]])
                    .sort((a,b) => a[1] - b[1]);
  Plotly.react('variety-chart', [{{
    type: 'bar',
    orientation: 'h',
    y: pairs.map(p => p[0]),
    x: pairs.map(p => p[1]),
    marker: {{
      color: pairs.map(p => varColor(p[0])),
      line: {{color: 'rgba(0,0,0,.15)', width: .5}}
    }},
    hovertemplate: '<b>%{{y}}</b><br>%{{x}} vineyards<extra></extra>',
    text: pairs.map(p => p[1]),
    textposition: 'outside',
    textfont: {{size: 11, color: '#2a1f14'}}
  }}], {{
    xaxis: {{title: 'Number of vineyards', rangemode: 'tozero'}},
    yaxis: {{automargin: true}},
    height: Math.max(300, pairs.length * 36 + 80),
    margin: {{l: 180, r: 60, t: 20, b: 50}},
    plot_bgcolor: '#faf9f5',
    paper_bgcolor: '#ffffff',
    font: {{family: 'Source Sans 3, sans-serif', color: '#2a1f14'}},
    hoverlabel: {{bgcolor: '#1e3d18', font: {{color: '#fff'}}}},
    showlegend: false
  }}, PLY_CFG);
}}

// ── Stacked bar (county or AVA) ───────────────────────────────────────
function buildStackedChart(elemId, decade, regionKey, topRegions) {{
  const d = PER_DECADE[decade][regionKey];
  // Build traces: one per variety in TOP_VARIETIES + Other
  const allVars = [...TOP_VARIETIES, 'Other'];
  const traces = allVars.map(v => {{
    const counts = d[v] || topRegions.map(() => 0);
    return {{
      type: 'bar',
      name: v,
      x: topRegions,
      y: counts,
      marker: {{color: varColor(v), line: {{color: 'rgba(255,255,255,.3)', width: .5}}}},
      hovertemplate: `<b>%{{x}}</b><br>${{v}}: %{{y}} vineyards<extra></extra>`
    }};
  }}).filter(t => t.y.some(c => c > 0));  // drop zero-only traces

  Plotly.react(elemId, traces, {{
    barmode: 'stack',
    xaxis: {{title: '', tickangle: -35, automargin: true}},
    yaxis: {{title: 'Variety appearances'}},
    height: 460,
    margin: {{l: 50, r: 20, t: 20, b: 120}},
    plot_bgcolor: '#faf9f5',
    paper_bgcolor: '#ffffff',
    font: {{family: 'Source Sans 3, sans-serif', color: '#2a1f14', size: 11}},
    legend: {{
      orientation: 'h', y: -0.55, x: 0,
      font: {{size: 10}},
      bgcolor: 'rgba(0,0,0,0)'
    }},
    hoverlabel: {{bgcolor: '#1e3d18', font: {{color: '#fff'}}}}
  }}, PLY_CFG);
}}

// ── PCT chart (static) ────────────────────────────────────────────────
Plotly.newPlot('pct-chart', PCT_TRACES, {{
  barmode: 'stack',
  xaxis: {{title: 'Percentage (%)', range: [0, 100]}},
  yaxis: {{automargin: true}},
  height: Math.max(400, PCT_NAMES.length * 28 + 100),
  legend: {{title: {{text: 'Variety'}}, orientation: 'v', x: 1.02}},
  margin: {{l: 240, r: 160, t: 20, b: 50}},
  plot_bgcolor: '#faf9f5',
  paper_bgcolor: '#ffffff',
  font: {{family: 'Source Sans 3, sans-serif', color: '#2a1f14'}},
  hoverlabel: {{bgcolor: '#1e3d18', font: {{color: '#fff'}}}}
}}, PLY_CFG);

// ── Overall top-10 (static) ───────────────────────────────────────────
const OV_VARS   = {js_ov_vars};
const OV_COUNTS = {js_ov_counts};
const OV_COLORS = {js_ov_colors};
Plotly.newPlot('overall-chart', [{{
  type: 'bar',
  orientation: 'h',
  y: OV_VARS,
  x: OV_COUNTS,
  marker: {{color: OV_COLORS, line: {{color: '#b8923a', width: .8}}}},
  hovertemplate: '<b>%{{y}}</b><br>%{{x}} vineyards<extra></extra>',
  text: OV_COUNTS,
  textposition: 'outside',
  textfont: {{size: 12, color: '#2a1f14'}}
}}], {{
  xaxis: {{title: 'Number of vineyards', dtick: 10}},
  yaxis: {{automargin: true}},
  height: 440,
  margin: {{l: 200, r: 60, t: 20, b: 50}},
  plot_bgcolor: '#faf9f5',
  paper_bgcolor: '#ffffff',
  font: {{family: 'Source Sans 3, sans-serif', color: '#2a1f14'}},
  hoverlabel: {{bgcolor: '#1e3d18', font: {{color: '#fff'}}}},
  showlegend: false
}}, PLY_CFG);

// ── Slider logic ──────────────────────────────────────────────────────
const slider  = document.getElementById('decade-slider');
const display = document.getElementById('decade-display');
const vyCount = document.getElementById('vy-count');

function updateAll(idx) {{
  const decade = DECADES[idx];
  const d = PER_DECADE[decade];
  display.textContent = decade === 'All' ? 'All Decades' : decade;
  vyCount.textContent = `(${{d.n_vineyards}} vineyard${{d.n_vineyards !== 1 ? 's' : ''}})`;

  // Update slider track fill
  const pct = (idx / (DECADES.length - 1)) * 100;
  slider.style.background =
    `linear-gradient(to right, var(--green-mid) 0%, var(--green-mid) ${{pct}}%, var(--border) ${{pct}}%, var(--border) 100%)`;

  buildVarietyChart(decade);
  buildStackedChart('county-chart', decade, 'county', TOP_COUNTIES);
  buildStackedChart('ava-chart',    decade, 'ava',    TOP_AVAS);
}}

slider.addEventListener('input', e => updateAll(+e.target.value));

// ── Initial render ────────────────────────────────────────────────────
updateAll(0);
</script>
</body>
</html>"""

with open("output/index.html", "w", encoding="utf-8") as f:
    f.write(HTML)

print(f"Written output/index.html  ({len(HTML):,} chars)")
