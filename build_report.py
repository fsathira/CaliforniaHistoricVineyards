"""
build_report.py
---------------
Generates output/index.html – a polished, interactive analytics page
styled after historicvineyardsociety.org.

Design tokens derived from the live HVS theme stylesheet:
  - Font:    CheltenhamOldSty (licensed) → Playfair Display (Google, closest free match)
             Nunito Sans for body/UI (explicitly referenced in hvs/style.css)
  - Colors:  #473b2b  dark walnut  (logo, primary text, headings)
             #9d5b37  sienna/rust  (accent, hovers, highlights)
             #786b58  warm brown   (buttons, secondary UI)
             #796C58  mid brown    (logo SVG fill colour)
             #ffffff  white        (page background)
             #ccc     light grey   (borders, dotted rules)
  - h1/h2:  font-weight normal, Playfair Display
  - h3:     uppercase, letter-spacing 1px
  - Buttons: uppercase, letter-spacing .5px, padding 10px 15px
"""

import csv, json, collections, re, urllib.request

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
        "u": item.get("url", ""),        # HVS page URL
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

# ── Japanese traditional colour palette (和色 wa-shoku) ────────────────────
# User-specified assignments adjusted to fit traditional Japanese pigments.
JP_SPECIFIC = {
    "Zinfandel":          "#F47B20",  # 柿色 kaki-iro    – persimmon orange
    "Carignan":           "#C4A46B",  # 砂色 suna-iro    – sand / light brown
    "Petite Sirah":       "#C0273F",  # 紅色 beni-iro    – crimson
    "Cabernet Sauvignon": "#E8B218",  # 山吹色 yamabuki  – golden yellow
    "Pinot Noir":         "#6B1E3C",  # 葡萄色 budō-iro  – grape / burgundy
    "Grenache":           "#E8A0B4",  # 桜色 sakura-iro  – cherry-blossom pink
    "Syrah":              "#81AD52",  # 若草色 wakakusa  – young-grass green
}
# Remaining slots filled from a curated wa-shoku fallback sequence
JP_FALLBACK = [
    "#4B2660",  # 紫紺 shikon       – indigo-purple
    "#B5294F",  # 茜色 akane-iro    – madder red
    "#9B8EC4",  # 藤色 fuji-iro     – wisteria purple
    "#2B6EA8",  # 縹色 hanada-iro   – sail-canvas blue
    "#DC6B56",  # 珊瑚色 sango-iro  – coral
    "#C88B2A",  # 黄金色 kogane     – amber gold
    "#5BB0B0",  # 浅葱色 asagi      – pale teal
    "#2A7A5A",  # 常磐色 tokiwa     – evergreen
]
_fb = iter(JP_FALLBACK)
VAR_COLOR = {}
for v in TOP_VARIETIES:
    VAR_COLOR[v] = JP_SPECIFIC.get(v) or next(_fb)
VAR_COLOR["Other"] = "#B0A8A0"   # 銀鼠 gin-nezumi – silver grey

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
    """Normalized stacked data for Plotly.

    Each vineyard contributes exactly 1.0 total across its varieties so bar
    heights equal the number of vineyards (not raw variety appearances):
      • If explicit pct data exists, use pct / sum(pcts) as weights.
      • Otherwise each of its N varieties contributes 1/N.
    """
    region_data = {r: collections.defaultdict(float) for r in top_regions}
    for vy in subset:
        r = vy[region_key]
        if r not in region_data:
            continue
        if vy["pct"]:
            total = sum(vy["pct"].values())
            if total > 0:
                for v, p in vy["pct"].items():
                    region_data[r][v] += p / total
        else:
            n = len(vy["v"])
            if n:
                w = 1.0 / n
                for v in vy["v"]:
                    region_data[r][v] += w
    result = {}
    for v in top_vars:
        result[v] = [round(region_data[r][v], 4) for r in top_regions]
    result["Other"] = []
    for r in top_regions:
        other = sum(cnt for var, cnt in region_data[r].items() if var not in top_vars)
        result["Other"].append(round(other, 4))
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

# ── Timeline breakdown by county / AVA / variety ──────────────────────────
TL_DECADES_LIST = DECADES_ORDERED[1:]   # ['1860s', '1870s', ..., '1970s']

# Categorical palette for county / AVA colouring in the timeline
TL_CAT_PALETTE = [
    "#5B8EC0","#8BC08B","#E8884A","#9B7EC0","#E8C858",
    "#C07898","#50A898","#C8885A","#7898D8","#A8C070",
    "#D87898","#6898A8","#B8A050","#A87098","#70B870",
    "#D8A070","#7898C0","#C8C058","#B88870","#90C8B8",
]
COUNTY_COLOR = {c: TL_CAT_PALETTE[i % len(TL_CAT_PALETTE)] for i, c in enumerate(TOP_COUNTIES)}
COUNTY_COLOR["Other"] = "#B0A8A0"
AVA_COLOR    = {a: TL_CAT_PALETTE[i % len(TL_CAT_PALETTE)] for i, a in enumerate(TOP_AVAS)}
AVA_COLOR["Other"] = "#B0A8A0"

# By county — each vineyard belongs to exactly one county → raw counts
timeline_county = {c: [] for c in TOP_COUNTIES + ["Other"]}
for dec in TL_DECADES_LIST:
    sub = filter_by_decade(dec)
    ctr = collections.Counter(vy["c"] for vy in sub if vy["c"])
    for c in TOP_COUNTIES:
        timeline_county[c].append(ctr.get(c, 0))
    timeline_county["Other"].append(
        sum(v for k, v in ctr.items() if k not in TOP_COUNTIES))

# By AVA — raw counts
timeline_ava = {a: [] for a in TOP_AVAS + ["Other"]}
for dec in TL_DECADES_LIST:
    sub = filter_by_decade(dec)
    ctr = collections.Counter(vy["a"] for vy in sub if vy["a"])
    for a in TOP_AVAS:
        timeline_ava[a].append(ctr.get(a, 0))
    timeline_ava["Other"].append(
        sum(v for k, v in ctr.items() if k not in TOP_AVAS))

# By variety — 1/N normalized so bar heights still equal vineyard count
timeline_variety = {v: [] for v in TOP_VARIETIES + ["Other"]}
for dec in TL_DECADES_LIST:
    sub = filter_by_decade(dec)
    vtot = collections.defaultdict(float)
    for vy in sub:
        if vy["pct"]:
            s = sum(vy["pct"].values())
            if s > 0:
                for v, p in vy["pct"].items():
                    vtot[v] += p / s
        else:
            n = len(vy["v"])
            if n:
                for v in vy["v"]:
                    vtot[v] += 1.0 / n
    for var in TOP_VARIETIES:
        timeline_variety[var].append(round(vtot.get(var, 0), 4))
    timeline_variety["Other"].append(
        round(sum(v for k, v in vtot.items() if k not in TOP_VARIETIES), 4))

# ── Section 1: pct stacked bar traces ─────────────────────────────────────
pct_vineyard_names = [p["name"] for p in PCT_VINEYARDS]
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
js_tl_decades   = json.dumps(TL_DECADES_LIST)
js_tl_county    = json.dumps(timeline_county)
js_tl_ava       = json.dumps(timeline_ava)
js_tl_variety   = json.dumps(timeline_variety)
js_county_color = json.dumps(COUNTY_COLOR)
js_ava_color    = json.dumps(AVA_COLOR)
js_pct_traces   = json.dumps(pct_traces)
js_pct_names    = json.dumps(pct_vineyard_names)
js_dec_ordered  = json.dumps(DECADES_ORDERED)

# Overall top10 for static chart
ov_top10 = all_var_ctr.most_common(10)
js_ov_vars   = json.dumps([v for v,_ in reversed(ov_top10)])
js_ov_counts = json.dumps([c for _,c in reversed(ov_top10)])
js_ov_colors = json.dumps([VAR_COLOR.get(v, VAR_COLOR["Other"]) for v,_ in reversed(ov_top10)])

# ── AVA GeoJSON fetch & vineyard injection ──────────────────────────────────
def _rdp_iter(pts, eps):
    """Ramer-Douglas-Peucker simplification (iterative — no recursion limit)."""
    if len(pts) < 3:
        return pts
    mask  = [True] * len(pts)
    stack = [(0, len(pts) - 1)]
    while stack:
        s, e = stack.pop()
        if e - s < 2:
            continue
        x0, y0 = pts[s];  xe, ye = pts[e]
        dx, dy  = xe - x0, ye - y0
        denom   = (dx*dx + dy*dy) ** 0.5 or 1e-9
        md, mi  = 0.0, s
        for i in range(s + 1, e):
            d = abs(dx*(y0 - pts[i][1]) - (x0 - pts[i][0])*dy) / denom
            if d > md:
                md, mi = d, i
        if md > eps:
            stack.append((s, mi));  stack.append((mi, e))
        else:
            for i in range(s + 1, e):
                mask[i] = False
    return [p for p, keep in zip(pts, mask) if keep]

def _simplify_ring(ring, eps):
    """Simplify a GeoJSON ring (closed polygon boundary).

    GeoJSON rings are closed: first point == last point.  We open the ring
    (drop the duplicate end), run RDP on the open chain, then re-close it.
    This avoids the degenerate case where start==end collapses every interior
    point to distance 0.
    """
    if len(ring) < 4:
        return ring
    # Detect closed ring (first pt == last pt in GeoJSON convention)
    closed = (ring[0] == ring[-1])
    pts    = ring[:-1] if closed else ring
    if len(pts) < 3:
        return ring
    s = _rdp_iter(pts, eps)
    if len(s) < 3:
        s = pts                             # refuse to collapse below 3 pts
    if closed:
        s = s + [s[0]]                      # re-close the ring
    return s

def _simplify_geom(geom, eps=0.005):
    t = geom["type"]
    if t == "Polygon":
        return {"type": "Polygon",
                "coordinates": [_simplify_ring(r, eps) for r in geom["coordinates"]]}
    if t == "MultiPolygon":
        return {"type": "MultiPolygon",
                "coordinates": [[_simplify_ring(r, eps) for r in poly]
                                for poly in geom["coordinates"]]}
    return geom

def _norm_ava(name):
    return re.sub(r'[^a-z0-9]', '', name.lower())

# Build lookup: normalised AVA name → list of vineyard dicts for map popups
_ava_lookup = collections.defaultdict(list)
for _vy in vineyards:
    if _vy["a"]:
        _ava_lookup[_norm_ava(_vy["a"])].append({
            "name":      _vy["n"],
            "decade":    _vy["d"],
            "county":    _vy["c"],
            "varieties": _vy["v"][:8],
            "url":       _vy["u"],
        })

_AVA_ALIASES = {
    # GeoJSON official name (normalised) → vineyard-data name (normalised)
    _norm_ava("California Shenandoah Valley"): _norm_ava("Shenandoah Valley"),
}

def _match_ava(feat_name):
    """Return list of vineyards for a GeoJSON feature (exact match only)."""
    k = _norm_ava(feat_name)
    if k in _ava_lookup:
        return list(_ava_lookup[k])
    alias = _AVA_ALIASES.get(k)
    if alias and alias in _ava_lookup:
        return list(_ava_lookup[alias])
    return []

# Fetch California AVA GeoJSON from the UC Davis community AVA repository
# (California-specific file from avas_by_state/ — no state filtering needed)
_AVA_URL   = ("https://raw.githubusercontent.com/UCDavisLibrary/ava/"
              "master/avas_by_state/CA_avas.geojson")
_ava_geojson = None
try:
    print("Fetching California AVA GeoJSON …", flush=True)
    with urllib.request.urlopen(_AVA_URL, timeout=60) as _r:
        _raw = json.loads(_r.read())
    _ca_feats = []
    for _f in _raw["features"]:
        _p = _f.get("properties") or {}
        _vys              = _match_ava(_p.get("name", ""))
        _p["count"]       = len(_vys)
        _p["vineyards"]   = _vys
        _f["geometry"]    = _simplify_geom(_f["geometry"])
        _ca_feats.append(_f)
    _ava_geojson = {"type": "FeatureCollection", "features": _ca_feats}
    _matched = sum(f["properties"]["count"] for f in _ca_feats)
    print(f"  → {len(_ca_feats)} CA AVAs, {_matched} total vineyard matches",
          flush=True)
except Exception as _e:
    print(f"Warning: AVA GeoJSON fetch failed ({_e}); map will be empty.",
          flush=True)

js_ava_geojson = json.dumps(
    _ava_geojson or {"type": "FeatureCollection", "features": []})

# ── Load and inline the official HVS logo ─────────────────────────────────
logo_raw = open("logo_hvs_full.svg", encoding="utf-8").read()
logo_raw = re.sub(r'<\?xml[^>]+\?>', '', logo_raw)
logo_raw = re.sub(r'<!DOCTYPE[^>]+>', '', logo_raw).strip()
logo_raw = re.sub(r'\bwidth="[^"]*"', '', logo_raw, count=1)
logo_raw = re.sub(r'\bheight="[^"]*"', '', logo_raw, count=1)
logo_raw = logo_raw.replace('<svg ', '<svg aria-label="Historic Vineyard Society" ', 1)

# ── HTML Template – Part 1: head, CSS, body open, static sections ──────────
HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>California Historic Vineyards – Interactive Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;1,400&family=Nunito+Sans:wght@300;400;600&display=swap" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
/* ── Reset ─────────────────────────────────────────── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
h1, h2, h3, h4, p, ol, ul {{ margin: 0; padding: 0; }}
img {{ border: 0; max-width: 100%; height: auto; vertical-align: bottom; }}
html {{ scroll-behavior: smooth; overflow-y: scroll; }}

/* ── HVS design tokens ─────────────────────────────── */
/* Sourced from historicvineyardsociety.org/wp-content/themes/hvs/style.css */
:root {{
  --walnut:     #473b2b;  /* logo, headings, primary text */
  --sienna:     #9d5b37;  /* accent, hovers, highlights   */
  --brown:      #786b58;  /* buttons, secondary UI        */
  --bg:         #ffffff;
  --bg-light:   #f5f2ee;  /* section backgrounds          */
  --border:     #cccccc;
  --text:       #473b2b;
  --text-light: #777777;
  --white:      #ffffff;
  --font-serif: 'Playfair Display', Georgia, serif;
  --font-sans:  'Nunito Sans', Helvetica, Arial, sans-serif;
  --max-w:      1100px;
  --pad:        60px;
}}

body {{
  font-family: var(--font-sans);
  font-size: 16px;
  line-height: 1.5em;
  background: var(--bg);
  color: var(--text);
}}
h1, h2, h3 {{
  font-family: var(--font-serif);
  font-weight: normal;
  text-rendering: optimizeLegibility;
}}
h1 {{ font-size: 2.5em; line-height: 1em; }}
h2 {{ font-size: 1.5em; line-height: 1em; margin-top: 1.5em; margin-bottom: 1em; }}
h2:first-child {{ margin-top: 0; }}
h3 {{
  font-size: 1.25em;
  line-height: 1.125em;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-top: 2em;
  margin-bottom: 1em;
}}
a {{ text-decoration: none; color: var(--sienna); transition: color .25s ease-out; }}
a:hover {{ color: var(--walnut); }}
p {{ margin-bottom: 1em; }}
p:last-child {{ margin-bottom: 0; }}

/* ── Site header ───────────────────────────────────── */
.site-header {{
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  padding: 1.5em var(--pad);
}}
.header-inner {{
  max-width: var(--max-w);
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 2.5rem;
}}
.logo-header {{ flex-shrink: 0; line-height: 0; }}
.logo-header svg {{ width: auto; height: 100px; display: block; }}
.header-copy h1 {{
  color: var(--walnut);
  text-transform: uppercase;
  letter-spacing: 5px;
  font-size: 1.8em;
}}
.header-copy .tagline {{
  font-size: .85em;
  color: var(--text-light);
  margin-top: .5em;
  text-transform: uppercase;
  letter-spacing: .5px;
}}

/* ── Stats strip ───────────────────────────────────── */
.stats-strip {{
  background: var(--walnut);
  padding: .8em var(--pad);
}}
.stats-inner {{
  max-width: var(--max-w);
  margin: 0 auto;
  display: flex;
}}
.stat-box {{
  flex: 1;
  text-align: center;
  padding: .3em .5em;
  border-right: 1px solid rgba(255,255,255,.2);
}}
.stat-box:last-child {{ border-right: none; }}
.stat-box .num {{
  display: block;
  font-family: var(--font-serif);
  font-size: 1.6em;
  color: #fff;
  line-height: 1;
}}
.stat-box .lbl {{
  display: block;
  font-size: .65em;
  color: rgba(255,255,255,.7);
  text-transform: uppercase;
  letter-spacing: .08em;
}}

/* ── Sticky nav ────────────────────────────────────── */
nav.site-nav {{
  background: var(--walnut);
  position: sticky;
  top: 0;
  z-index: 200;
  border-bottom: 3px solid var(--sienna);
}}
nav.site-nav ul {{
  max-width: var(--max-w);
  margin: 0 auto;
  padding: 0 var(--pad);
  display: flex;
  list-style: none;
  flex-wrap: wrap;
}}
nav.site-nav a {{
  display: block;
  padding: .6em 10px;
  font-size: 14px;
  letter-spacing: .5px;
  text-transform: uppercase;
  color: rgba(255,255,255,.8);
  white-space: nowrap;
  border-bottom: 3px solid transparent;
  margin-bottom: -3px;
  transition: color .25s ease-out, border-color .25s ease-out;
}}
nav.site-nav a:hover {{ color: #fff; border-bottom-color: rgba(255,255,255,.6); }}

/* ── Main ──────────────────────────────────────────── */
.main {{
  max-width: var(--max-w);
  margin: 3em auto;
  padding: 0 var(--pad) 5em;
  display: flex;
  flex-direction: column;
  gap: 3em;
}}

/* ── Section card ──────────────────────────────────── */
.sc {{
  background: var(--bg);
  border: 1px solid var(--border);
  box-shadow: 0 1px 4px rgba(71,59,43,.08);
}}
.sc-head {{
  padding: 1em 1.5em .7em;
  border-bottom: 1px solid var(--border);
}}
.sc-head h2 {{ color: var(--walnut); margin: 0; font-size: 1.35em; }}
.sc-rule {{
  border: none;
  border-top: 2px solid var(--sienna);
  width: 50px;
  margin: .6em 0 1.2em;
}}
.sc-body {{ padding: 1.5em 1.5em 2em; }}
.subtitle {{
  font-size: .875em;
  color: var(--text-light);
  margin-bottom: 1.2em;
  font-style: italic;
  margin-top: 0;
}}

/* ── Timeline toggle buttons ──────────────────────────────────────────── */
.tl-toggles {{
  display: flex;
  align-items: center;
  gap: .45em;
  margin-bottom: 1.1em;
  flex-wrap: wrap;
}}
.tl-toggle-label {{
  font-size: .72em;
  text-transform: uppercase;
  letter-spacing: .5px;
  color: var(--text-light);
  font-weight: 600;
  margin-right: .2em;
  flex-shrink: 0;
}}
.tl-btn {{
  font-family: var(--font-sans);
  font-size: .76em;
  padding: .28em 1em;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-light);
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: .4px;
  border-radius: 2px;
  transition: background .15s, color .15s, border-color .15s;
}}
.tl-btn:hover {{ border-color: var(--sienna); color: var(--sienna); }}
.tl-btn.active {{ background: var(--walnut); color: #fff; border-color: var(--walnut); }}

/* ── Inline decade strip (lives inside the chart section) ─────────────── */
.decade-strip {{
  display: flex;
  align-items: center;
  gap: 1.5em;
  background: var(--bg-light);
  border: 1px solid var(--border);
  border-left: 3px solid var(--sienna);
  padding: .55em 1.2em .55em .9em;
  margin-bottom: 1.8em;
}}
.ds-label {{
  font-size: .72em;
  text-transform: uppercase;
  letter-spacing: .5px;
  color: var(--text-light);
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}}
.ds-value {{
  font-family: var(--font-serif);
  font-size: 1.1em;
  color: var(--walnut);
  white-space: nowrap;
  flex-shrink: 0;
  min-width: 7.5em;
}}
.ds-value small {{
  font-family: var(--font-sans);
  font-size: .65em;
  color: var(--text-light);
  font-weight: 300;
  margin-left: .3em;
}}
.ds-slider-wrap {{
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: .1em;
  min-width: 0;
}}
.slider-label-row {{
  display: flex;
  justify-content: space-between;
  font-size: .62em;
  color: var(--text-light);
  user-select: none;
  letter-spacing: .2px;
}}
input[type=range] {{
  -webkit-appearance: none;
  width: 100%;
  height: 4px;
  background: var(--border);
  border-radius: 2px;
  outline: none;
  cursor: pointer;
}}
input[type=range]::-webkit-slider-thumb {{
  -webkit-appearance: none;
  width: 16px; height: 16px;
  background: var(--walnut);
  border: 3px solid var(--sienna);
  border-radius: 50%;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(0,0,0,.2);
}}
input[type=range]::-moz-range-thumb {{
  width: 16px; height: 16px;
  background: var(--walnut);
  border: 3px solid var(--sienna);
  border-radius: 50%;
  cursor: pointer;
}}

/* ── Two-column ────────────────────────────────────── */
.two-col {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2em;
}}

/* ── Accordion ─────────────────────────────────────── */
details.accordion {{
  border-top: 2px dotted var(--border);
}}
details.accordion:last-child {{ border-bottom: 2px dotted var(--border); }}
details.accordion summary {{
  cursor: pointer;
  padding: .6em 0;
  font-weight: 600;
  font-size: .95em;
  list-style: none;
  display: flex;
  align-items: center;
  gap: .5em;
  user-select: none;
  color: var(--walnut);
  transition: color .25s ease-out;
}}
details.accordion summary:hover {{ color: var(--sienna); }}
details.accordion summary::-webkit-details-marker {{ display: none; }}
details.accordion summary::before {{
  content: '▶';
  font-size: .6em;
  transition: transform .15s;
  color: var(--sienna);
  flex-shrink: 0;
}}
details[open].accordion summary::before {{ transform: rotate(90deg); }}
details.accordion table {{ margin: .5em 0 1em; }}
.badge {{
  font-size: .72em;
  background: var(--bg-light);
  color: var(--text-light);
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: .1em .5em;
  margin-left: auto;
  font-weight: 400;
  letter-spacing: .3px;
}}

/* ── Tables ────────────────────────────────────────── */
table {{ width: 100%; border-collapse: collapse; font-size: .875em; }}
th {{
  text-align: left;
  padding: .5em 1em;
  font-weight: 600;
  color: var(--text-light);
  font-size: .8em;
  text-transform: uppercase;
  letter-spacing: .5px;
}}
td {{
  padding: .5em 1em;
  border-top: 2px dotted var(--border);
  vertical-align: middle;
  transition: border-top-style .25s ease;
}}
tr:hover td {{ border-top-style: solid; }}
.rank {{ color: var(--sienna); font-size: .8em; width: 28px; font-weight: 700; }}
.bar-bg {{
  background: var(--bg-light);
  border: 1px solid var(--border);
  border-radius: 1px;
  height: 8px;
  display: inline-block;
  width: 120px;
  vertical-align: middle;
}}
.bar-fill {{
  background: var(--brown);
  border-radius: 1px;
  height: 8px;
  display: inline-block;
}}
.count-cell {{ display: flex; align-items: center; gap: 8px; white-space: nowrap; }}

/* ── Footer ────────────────────────────────────────── */
.site-footer {{
  background: var(--walnut);
  color: rgba(255,255,255,.65);
  padding: 2em var(--pad);
  font-size: .85em;
  border-top: 3px solid var(--sienna);
}}
.site-footer p {{ text-transform: uppercase; letter-spacing: .5px; margin: 0; }}
.site-footer a {{ color: rgba(255,255,255,.85); }}

/* ── Responsive ─────────────────────────────────────── */
/* ── AVA Map ─────────────────────────────────────────── */
#map-wrap {{
  display: flex;
  gap: 1.5em;
  align-items: flex-start;
}}
#ava-map {{
  flex: 2;
  min-width: 0;
  height: 560px;
  border: 1px solid var(--border);
  border-radius: 2px;
  z-index: 1;
}}
#ava-panel {{
  flex: 1;
  min-width: 240px;
  max-height: 560px;
  overflow-y: auto;
  border: 1px solid var(--border);
  padding: 1.1em 1.2em;
  background: var(--bg-light);
  border-radius: 2px;
}}
#ava-panel .ava-panel-title {{
  font-family: var(--font-serif);
  font-size: 1.05em;
  font-weight: normal;
  color: var(--walnut);
  margin: 0 0 .5em;
  text-transform: none;
  letter-spacing: 0;
}}
.ava-hint {{
  font-size: .875em;
  color: var(--text-light);
  font-style: italic;
}}
.ava-count {{
  font-size: .78em;
  color: var(--sienna);
  font-weight: 600;
  margin-bottom: .8em;
  text-transform: uppercase;
  letter-spacing: .3px;
}}
.ava-none {{
  font-size: .85em;
  color: var(--text-light);
  font-style: italic;
}}
.vy-list {{ display: flex; flex-direction: column; gap: .65em; }}
.vy-card {{
  background: #fff;
  border: 1px solid var(--border);
  border-left: 3px solid var(--sienna);
  padding: .55em .8em;
  border-radius: 2px;
}}
.vy-card-name {{
  font-weight: 600;
  font-size: .88em;
  margin-bottom: .18em;
  color: var(--walnut);
}}
.vy-card-name a {{ color: var(--sienna); }}
.vy-card-name a:hover {{ color: var(--walnut); }}
.vy-card-meta {{
  font-size: .74em;
  color: var(--text-light);
  margin-bottom: .3em;
}}
.vy-card-chips {{ display: flex; flex-wrap: wrap; gap: .22em; }}
.vy-chip {{
  font-size: .62em;
  padding: .15em .48em;
  border-radius: 2px;
  color: #fff;
  font-weight: 600;
  text-shadow: 0 1px 1px rgba(0,0,0,.3);
  white-space: nowrap;
}}
/* Leaflet choropleth legend */
.map-legend {{
  background: #fff;
  border: 1px solid var(--border);
  padding: .55em .85em;
  font-family: var(--font-sans);
  font-size: .78em;
  line-height: 1.65;
  border-radius: 2px;
  box-shadow: 0 1px 4px rgba(0,0,0,.15);
}}
.map-legend strong {{
  font-size: .9em;
  text-transform: uppercase;
  letter-spacing: .3px;
  color: var(--walnut);
}}
.map-legend i {{
  width: 13px;
  height: 13px;
  display: inline-block;
  margin-right: .4em;
  vertical-align: middle;
  border: 1px solid rgba(0,0,0,.1);
  border-radius: 1px;
}}
@media (max-width: 768px) {{
  :root {{ --pad: 20px; }}
  .header-inner {{ flex-direction: column; text-align: center; }}
  .logo-header svg {{ height: 70px; }}
  .two-col {{ grid-template-columns: 1fr; }}
  h1 {{ font-size: 1.6em; }}
  nav.site-nav ul {{ padding: 0 1em; }}
  .stats-inner {{ flex-wrap: wrap; }}
  .stat-box {{ min-width: 90px; }}
  .decade-strip {{ flex-direction: column; align-items: flex-start; gap: .4em; }}
  .ds-slider-wrap {{ width: 100%; }}
  #map-wrap {{ flex-direction: column; }}
  #ava-map {{ height: 380px; }}
  #ava-panel {{ max-height: 300px; }}
}}
</style>
</head>
<body>

<!-- HEADER -->
<header class="site-header">
  <div class="header-inner">
    <div class="logo-header">{logo_raw}</div>
    <div class="header-copy">
      <h1>California Historic Vineyards</h1>
      <p class="tagline">
        Data source:
        <a href="https://historicvineyardsociety.org">historicvineyardsociety.org</a>
        &nbsp;·&nbsp; {n_total} vineyards catalogued
      </p>
    </div>
  </div>
</header>

<!-- STATS -->
<div class="stats-strip">
  <div class="stats-inner">
    <div class="stat-box"><span class="num">{n_total}</span><span class="lbl">Vineyards</span></div>
    <div class="stat-box"><span class="num">{n_avas}</span><span class="lbl">AVAs</span></div>
    <div class="stat-box"><span class="num">{n_counties}</span><span class="lbl">Counties</span></div>
    <div class="stat-box"><span class="num">{n_varieties}</span><span class="lbl">Varieties</span></div>
    <div class="stat-box"><span class="num">{n_pct}</span><span class="lbl">With % data</span></div>
  </div>
</div>

<!-- NAV -->
<nav class="site-nav">
  <ul>
    <li><a href="#sec-timeline">Planting Timeline</a></li>
    <li><a href="#sec-map">AVA Map</a></li>
    <li><a href="#sec-interactive">By Decade</a></li>
    <li><a href="#sec-pct">Variety %</a></li>
    <li><a href="#sec-overall">Overall Top 10</a></li>
    <li><a href="#sec-tables">Region Tables</a></li>
  </ul>
</nav>

<div class="main">

<!-- TIMELINE -->
<section class="sc" id="sec-timeline">
  <div class="sc-head"><h2>Planting Timeline</h2></div>
  <div class="sc-body">
    <p class="subtitle">Number of vineyards planted per decade across all {n_total} catalogued sites. Toggle to break down by county, AVA, or variety.</p>
    <hr class="sc-rule">
    <div class="tl-toggles">
      <span class="tl-toggle-label">Color by:</span>
      <button class="tl-btn active" data-mode="simple">Decade</button>
      <button class="tl-btn" data-mode="county">County</button>
      <button class="tl-btn" data-mode="ava">AVA</button>
      <button class="tl-btn" data-mode="variety">Variety</button>
    </div>
    <div id="timeline-chart"></div>
  </div>
</section>

<!-- AVA MAP -->
<section class="sc" id="sec-map">
  <div class="sc-head"><h2>California AVA Map</h2></div>
  <div class="sc-body">
    <p class="subtitle">American Viticultural Areas (AVAs) colored by number of catalogued historic vineyards. Click any AVA to explore its vineyards.</p>
    <hr class="sc-rule">
    <div id="map-wrap">
      <div id="ava-map"></div>
      <div id="ava-panel">
        <p class="ava-hint">Click on an AVA region to see the historic vineyards it contains.</p>
      </div>
    </div>
  </div>
</section>

<!-- VARIETY + COUNTY + AVA — all controlled by the inline decade slider -->
<section class="sc" id="sec-interactive">
  <div class="sc-head"><h2>Variety &amp; Geographic Distribution</h2></div>
  <div class="sc-body">

    <!-- Compact inline decade filter -->
    <div class="decade-strip">
      <span class="ds-label">Decade planted</span>
      <span class="ds-value" id="decade-display">All Decades<small id="vy-count"></small></span>
      <div class="ds-slider-wrap">
        <input type="range" id="decade-slider" min="0" max="12" value="0" step="1">
        <div class="slider-label-row">
          <span>All</span><span>1860s</span><span>1870s</span><span>1880s</span><span>1890s</span>
          <span>1900s</span><span>1910s</span><span>1920s</span><span>1930s</span><span>1940s</span>
          <span>1950s</span><span>1960s</span><span>1970s</span>
        </div>
      </div>
    </div>

    <!-- Variety bar -->
    <h3 id="sec-decade" style="margin-top:0">Top Varieties</h3>
    <p class="subtitle">Number of vineyards containing each variety — filtered by decade above.</p>
    <div id="variety-chart"></div>

    <!-- County + AVA two-col -->
    <div class="two-col" style="margin-top:2.5em">
      <div>
        <h3 id="sec-county">By County</h3>
        <p class="subtitle">Top 15 counties, stacked by variety. Bar height = vineyard equivalents (each vineyard contributes&nbsp;1 total, split&nbsp;1/N across its N varieties).</p>
        <div id="county-chart"></div>
      </div>
      <div>
        <h3 id="sec-ava">By AVA</h3>
        <p class="subtitle">Top 15 AVAs, same normalization as County chart.</p>
        <div id="ava-chart"></div>
      </div>
    </div>

  </div>
</section>

<!-- VARIETY % -->
<section class="sc" id="sec-pct">
  <div class="sc-head"><h2>Variety Composition</h2></div>
  <div class="sc-body">
    <p class="subtitle">{n_pct} vineyards have explicit variety percentages. Only varieties &ge; 5% shown.</p>
    <hr class="sc-rule">
    <div id="pct-chart"></div>
    <table style="margin-top:1.5em">
      <thead>
        <tr><th>Vineyard</th><th>AVA</th><th>County</th><th>Decade</th><th>Varieties (&ge;5%)</th></tr>
      </thead>
      <tbody>
"""

# ── PCT table rows (dynamic) ───────────────────────────────────────────────
for p in PCT_VINEYARDS:
    var_str = ", ".join(
        f"{v} ({round(pct)}%)"
        for v, pct in sorted(p["varieties"].items(), key=lambda x: -x[1])
    )
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

<!-- OVERALL TOP 10 -->
<section class="sc" id="sec-overall">
  <div class="sc-head"><h2>Overall Top 10 Varieties</h2></div>
  <div class="sc-body">
    <p class="subtitle">Ranked by number of vineyards containing each variety, regardless of percentage — all 197 vineyards.</p>
    <hr class="sc-rule">
    <div id="overall-chart"></div>
  </div>
</section>

<!-- REGION TABLES -->
<section class="sc" id="sec-tables">
  <div class="sc-head"><h2>Top Varieties by AVA</h2></div>
  <div class="sc-body">
    <p class="subtitle">Expand an AVA to see how many of its vineyards contain each variety.</p>
    <hr class="sc-rule">
"""

# ── Accordion tables (dynamic) ─────────────────────────────────────────────
ava_variety_data = collections.defaultdict(lambda: collections.Counter())
for vy in vineyards:
    if vy["a"]:
        for v in vy["v"]:
            ava_variety_data[vy["a"]][v] += 1

for ava_name in sorted(ava_variety_data.keys()):
    vc_data = ava_variety_data[ava_name]
    total = sum(vc_data.values())
    top10 = vc_data.most_common(10)
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

</div><!-- .main -->

<footer class="site-footer">
  <p>Data sourced from <a href="https://historicvineyardsociety.org">Historic Vineyard Society</a>
  &nbsp;·&nbsp; California Historic Vineyard Analysis &nbsp;·&nbsp; Built with Plotly.js</p>
</footer>

<script>
const PER_DECADE    = {js_per_decade};
const TOP_VARIETIES = {js_top_varieties};
const TOP_COUNTIES  = {js_top_counties};
const TOP_AVAS      = {js_top_avas};
const VAR_COLOR     = {js_var_color};
const DEC_TIMELINE  = {js_dec_timeline};
const PCT_TRACES    = {js_pct_traces};
const PCT_NAMES     = {js_pct_names};
const DECADES       = {js_dec_ordered};
const OV_VARS       = {js_ov_vars};
const OV_COUNTS     = {js_ov_counts};
const OV_COLORS     = {js_ov_colors};
const AVA_GEOJSON   = {js_ava_geojson};

const PLY_CFG = {{responsive: true, displayModeBar: false}};

const PLY_LAYOUT_BASE = {{
  plot_bgcolor:  '#f5f2ee',
  paper_bgcolor: '#ffffff',
  font: {{family: 'Nunito Sans, Helvetica, sans-serif', color: '#473b2b', size: 12}},
  hoverlabel: {{bgcolor: '#473b2b', font: {{color: '#fff', size: 12}}}},
}};

function vc(v) {{ return VAR_COLOR[v] || VAR_COLOR['Other']; }}

// ── Timeline breakdown data ────────────────────────────────────────
const TL_DECADES    = {js_tl_decades};
const TL_COUNTY     = {js_tl_county};
const TL_AVA        = {js_tl_ava};
const TL_VARIETY    = {js_tl_variety};
const COUNTY_COLOR  = {js_county_color};
const AVA_COLOR     = {js_ava_color};

// ── Timeline chart (togglable by county / AVA / variety) ──────────
function buildTimelineChart(mode) {{
  let traces, extraLayout;
  if (mode === 'simple') {{
    traces = [{{
      type: 'bar',
      x: TL_DECADES,
      y: TL_DECADES.map(d => DEC_TIMELINE[d]),
      marker: {{color: '#786b58', line: {{color: '#9d5b37', width: 1}}}},
      hovertemplate: '<b>%{{x}}</b><br>%{{y}} vineyards<extra></extra>'
    }}];
    extraLayout = {{
      showlegend: false,
      height: 320,
      margin: {{l: 60, r: 20, t: 10, b: 70}},
    }};
  }} else {{
    const dataMap  = mode === 'county' ? TL_COUNTY  : mode === 'ava' ? TL_AVA  : TL_VARIETY;
    const colorMap = mode === 'county' ? COUNTY_COLOR : mode === 'ava' ? AVA_COLOR : VAR_COLOR;
    traces = Object.entries(dataMap)
      .map(([name, counts]) => ({{
        type: 'bar', name,
        x: TL_DECADES, y: counts,
        marker: {{
          color: colorMap[name] || '#B0A8A0',
          line: {{color: 'rgba(255,255,255,.2)', width: .4}}
        }},
        hovertemplate: `<b>%{{x}}</b><br>${{name}}: %{{y:.2f}}<extra></extra>`
      }}))
      .filter(t => t.y.some(v => v > 0));
    extraLayout = {{
      barmode: 'stack',
      showlegend: true,
      height: 500,
      margin: {{l: 60, r: 20, t: 10, b: 175}},
      legend: {{orientation: 'h', y: -0.42, x: 0, font: {{size: 10}}, bgcolor: 'rgba(0,0,0,0)'}},
    }};
  }}
  Plotly.react('timeline-chart', traces,
    Object.assign({{}}, PLY_LAYOUT_BASE, {{
      xaxis: {{title: 'Decade planted', tickangle: -30}},
      yaxis: {{title: mode === 'variety' ? 'Vineyard equivalents' : 'Vineyards', dtick: 5}},
    }}, extraLayout),
    PLY_CFG
  );
}}

document.querySelectorAll('.tl-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.tl-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    buildTimelineChart(btn.dataset.mode);
  }});
}});

buildTimelineChart('simple');

// ── Variety bar ───────────────────────────────────────────────────
function buildVarietyChart(decade) {{
  const d = PER_DECADE[decade];
  const pairs = d.var_bar.vars.map((v,i) => [v, d.var_bar.counts[i]])
                              .sort((a,b) => a[1]-b[1]);
  Plotly.react('variety-chart', [{{
    type: 'bar', orientation: 'h',
    y: pairs.map(p=>p[0]),
    x: pairs.map(p=>p[1]),
    marker: {{
      color: pairs.map(p=>vc(p[0])),
      line: {{color: 'rgba(0,0,0,.12)', width: .5}}
    }},
    hovertemplate: '<b>%{{y}}</b><br>%{{x}} vineyards<extra></extra>',
    text: pairs.map(p=>p[1]),
    textposition: 'outside',
    textfont: {{size: 11, color: '#473b2b'}}
  }}], Object.assign({{}}, PLY_LAYOUT_BASE, {{
    xaxis: {{title: 'Number of vineyards', rangemode: 'tozero'}},
    yaxis: {{automargin: true}},
    height: Math.max(280, pairs.length * 36 + 70),
    margin: {{l: 180, r: 60, t: 10, b: 50}},
    showlegend: false
  }}), PLY_CFG);
}}

// ── Stacked county/AVA bars ───────────────────────────────────────
function buildStackedChart(elemId, decade, regionKey, topRegions) {{
  const d = PER_DECADE[decade][regionKey];
  const allVars = [...TOP_VARIETIES, 'Other'];
  const traces = allVars.map(v => {{
    const counts = d[v] || topRegions.map(()=>0);
    return {{
      type: 'bar', name: v,
      x: topRegions, y: counts,
      marker: {{color: vc(v), line: {{color: 'rgba(255,255,255,.25)', width:.5}}}},
      hovertemplate: `<b>%{{x}}</b><br>${{v}}: %{{y}}<extra></extra>`
    }};
  }}).filter(t => t.y.some(c=>c>0));

  Plotly.react(elemId, traces, Object.assign({{}}, PLY_LAYOUT_BASE, {{
    barmode: 'stack',
    xaxis: {{tickangle: -40, automargin: true}},
    yaxis: {{title: 'Vineyard equivalents (normalized)'}},
    height: 460,
    margin: {{l: 50, r: 10, t: 10, b: 130}},
    legend: {{orientation:'h', y:-0.6, x:0, font:{{size:10}}, bgcolor:'rgba(0,0,0,0)'}},
  }}), PLY_CFG);
}}

// ── PCT chart (static) ────────────────────────────────────────────
Plotly.newPlot('pct-chart', PCT_TRACES, Object.assign({{}}, PLY_LAYOUT_BASE, {{
  barmode: 'stack',
  xaxis: {{title: 'Percentage (%)', range: [0, 100]}},
  yaxis: {{automargin: true}},
  height: Math.max(380, PCT_NAMES.length * 28 + 100),
  legend: {{title: {{text: 'Variety'}}, orientation: 'v', x: 1.02}},
  margin: {{l: 240, r: 160, t: 10, b: 50}},
}}), PLY_CFG);

// ── Overall top-10 (static) ───────────────────────────────────────
Plotly.newPlot('overall-chart', [{{
  type: 'bar', orientation: 'h',
  y: OV_VARS, x: OV_COUNTS,
  marker: {{color: OV_COLORS, line: {{color: '#9d5b37', width: .8}}}},
  hovertemplate: '<b>%{{y}}</b><br>%{{x}} vineyards<extra></extra>',
  text: OV_COUNTS, textposition: 'outside',
  textfont: {{size: 12, color: '#473b2b'}}
}}], Object.assign({{}}, PLY_LAYOUT_BASE, {{
  xaxis: {{title: 'Number of vineyards', dtick: 10}},
  yaxis: {{automargin: true}},
  height: 420,
  margin: {{l: 200, r: 60, t: 10, b: 50}},
  showlegend: false
}}), PLY_CFG);

// ── Slider ────────────────────────────────────────────────────────
const slider  = document.getElementById('decade-slider');
const display = document.getElementById('decade-display');
const vyCount = document.getElementById('vy-count');

function updateAll(idx) {{
  const decade = DECADES[idx];
  const d = PER_DECADE[decade];
  // display is a <span> whose first text node precedes the <small> child
  display.childNodes[0].textContent = decade === 'All' ? 'All Decades' : decade;
  vyCount.textContent = ` (${{d.n_vineyards}} vineyard${{d.n_vineyards!==1?'s':''}})`;
  const pct = (idx / (DECADES.length-1)) * 100;
  slider.style.background =
    `linear-gradient(to right, #786b58 0%, #786b58 ${{pct}}%, #ccc ${{pct}}%, #ccc 100%)`;
  buildVarietyChart(decade);
  buildStackedChart('county-chart', decade, 'county', TOP_COUNTIES);
  buildStackedChart('ava-chart',    decade, 'ava',    TOP_AVAS);
}}

slider.addEventListener('input', e => updateAll(+e.target.value));
updateAll(0);

// ── AVA Choropleth Map (Leaflet) ────────────────────────────────────────────
(function() {{
  if (typeof L === 'undefined') return;
  if (!AVA_GEOJSON || !AVA_GEOJSON.features || !AVA_GEOJSON.features.length) {{
    document.getElementById('ava-map').innerHTML =
      '<p style="padding:2em;color:#777;font-style:italic">Map data unavailable.</p>';
    return;
  }}

  const map = L.map('ava-map', {{
    center: [37.5, -119.5],
    zoom: 6,
    scrollWheelZoom: false,
  }});

  L.tileLayer(
    'https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png',
    {{
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' +
                   ' &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19,
    }}
  ).addTo(map);

  function getColor(n) {{
    return n >= 12 ? '#473b2b'
         : n >=  7 ? '#956c38'
         : n >=  4 ? '#b88c50'
         : n >=  2 ? '#d4b07a'
         : n >=  1 ? '#e8d5b0'
         :            '#f5f2ee';
  }}

  function layerStyle(feat) {{
    const n = feat.properties.count || 0;
    return {{
      fillColor:   getColor(n),
      weight:      1,
      opacity:     .8,
      color:       '#9d5b37',
      fillOpacity: n > 0 ? .72 : .3,
    }};
  }}

  const panel = document.getElementById('ava-panel');
  let active  = null;

  function showPanel(feat) {{
    const p    = feat.properties;
    const name = p.name || '';
    const vys  = p.vineyards || [];
    let h = `<h3 class="ava-panel-title">${{name}}</h3>`;
    if (!vys.length) {{
      h += '<p class="ava-none">No catalogued historic vineyards in this AVA.</p>';
    }} else {{
      h += `<p class="ava-count">${{vys.length}} historic vineyard${{vys.length !== 1 ? 's' : ''}}</p>`;
      h += '<div class="vy-list">';
      vys.forEach(vy => {{
        const chips = (vy.varieties || []).map(v =>
          `<span class="vy-chip" style="background:${{VAR_COLOR[v] || '#B0A8A0'}}">${{v}}</span>`
        ).join('');
        const nm   = vy.url
          ? `<a href="${{vy.url}}" target="_blank" rel="noopener">${{vy.name}}</a>`
          : vy.name;
        const meta = [vy.county, vy.decade].filter(Boolean).join(' \u00b7 ');
        h += `<div class="vy-card">`;
        h += `<div class="vy-card-name">${{nm}}</div>`;
        if (meta)  h += `<div class="vy-card-meta">${{meta}}</div>`;
        if (chips) h += `<div class="vy-card-chips">${{chips}}</div>`;
        h += `</div>`;
      }});
      h += '</div>';
    }}
    panel.innerHTML = h;
    panel.scrollTop = 0;
  }}

  function onEach(feat, layer) {{
    const n    = feat.properties.count || 0;
    const name = feat.properties.name  || '';
    layer.bindTooltip(
      `<b>${{name}}</b><br>${{n}} vineyard${{n !== 1 ? 's' : ''}}`,
      {{sticky: true}}
    );
    layer.on('click', function() {{
      if (active) active.setStyle(layerStyle(active.feature));
      layer.setStyle({{weight: 2.5, color: '#473b2b', fillOpacity: .9}});
      active = layer;
      showPanel(feat);
    }});
  }}

  L.geoJSON(AVA_GEOJSON, {{style: layerStyle, onEachFeature: onEach}}).addTo(map);

  // Choropleth legend
  const legend = L.control({{position: 'bottomright'}});
  legend.onAdd = function() {{
    const d = L.DomUtil.create('div', 'map-legend');
    d.innerHTML = '<strong>Vineyards</strong><br>';
    [[0,'0'],[1,'1'],[2,'2–3'],[4,'4–6'],[7,'7–11'],[12,'12+']].forEach(function(pair) {{
      d.innerHTML +=
        `<i style="background:${{getColor(pair[0] + .1)}}"></i>${{pair[1]}}<br>`;
    }});
    return d;
  }};
  legend.addTo(map);
}})();
</script>
</body>
</html>"""

with open("output/index.html", "w", encoding="utf-8") as f:
    f.write(HTML)

print(f"Written output/index.html  ({len(HTML):,} chars)")
