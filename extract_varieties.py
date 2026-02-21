"""
Extract grape varieties (with percentages where stated) from vineyard descriptions.

Uses claude-haiku-4-5 to reason over each description and return structured JSON.
Claude handles ambiguous language, historical vs. current plantings, inference, etc.

Run with ANTHROPIC_API_KEY set in your environment:
    export ANTHROPIC_API_KEY=sk-ant-...
    python extract_varieties.py

Resumes automatically from output/vineyard_varieties.json if interrupted.
Falls back to a lightweight regex extractor if no API key is present.
"""

import json
import os
import re
import time

INPUT_FILE  = "output/vineyards_raw.json"
OUTPUT_FILE = "output/vineyard_varieties.json"

# ---------------------------------------------------------------------------
# Claude-based extraction
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a viticulture expert extracting grape variety compositions from historic California vineyard descriptions.

Return a JSON object with exactly these fields:
- "varieties": list of objects, each with:
    - "name": canonical grape variety name, properly spelled and accented
      (e.g. "Mourvèdre" not "Mourvedre", "Petite Sirah" not "Petite syrah")
    - "pct": percentage as a float (0–100), or null if not stated or inferable
    - "inferred": true if the percentage was calculated rather than stated explicitly
- "notes": one sentence explaining any inference or ambiguity, or null

Rules:
1. ONLY include varieties currently planted in this vineyard.
   Ignore: varieties mentioned only in historical context, neighboring vineyards,
   what a winery does with the grapes, or what other owners planted elsewhere.
2. Inference: if some varieties have explicit percentages that sum to less than 100%,
   and one variety is described as "predominantly", "primarily", "mainly", or is
   clearly the dominant planting, infer its percentage as 100 minus the sum of others.
   Example: "predominantly Mourvèdre" + others summing to 25% → Mourvèdre = 75%.
3. "effectively 100% X" means X is ~100%; list any trace interplanted varieties with pct: null.
4. If no percentages are given at all, list varieties with pct: null.
5. If the description gives no variety information, return {"varieties": [], "notes": null}.
6. Return ONLY valid JSON — no markdown fences, no commentary outside the JSON.

Example input:
  "Two acres of predominantly Mourvèdre planted in 1910. Other varieties: Petite Sirah (10%),
   Syrah (6%), Carignan (4%), Peloursin (3%), Alicante Bouschet (2%). Also a few Zinfandel vines
   and nine whites of a variety called Helena (a cross of Zinfandel and Mondeuse noir)."

Example output:
  {"varieties": [
    {"name": "Mourvèdre",        "pct": 75.0, "inferred": true},
    {"name": "Petite Sirah",     "pct": 10.0, "inferred": false},
    {"name": "Syrah",            "pct":  6.0, "inferred": false},
    {"name": "Carignan",         "pct":  4.0, "inferred": false},
    {"name": "Peloursin",        "pct":  3.0, "inferred": false},
    {"name": "Alicante Bouschet","pct":  2.0, "inferred": false},
    {"name": "Zinfandel",        "pct": null, "inferred": false},
    {"name": "Helena",           "pct": null, "inferred": false}
  ],
  "notes": "Mourvèdre inferred as 100 - (10+6+4+3+2) = 75%."}
"""


def extract_with_claude(client, vineyard: dict) -> dict:
    """Call claude-haiku to extract variety data from a single vineyard."""
    name = vineyard.get("name", "")
    desc = vineyard.get("description", "").strip()

    if not desc:
        return {"varieties": [], "notes": "no description"}

    user_msg = f"Vineyard: {name}\n\nDescription:\n{desc}"

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = response.content[0].text.strip()
    # Strip accidental markdown fences
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"varieties": [], "notes": f"parse_error: {raw[:200]}"}


# ---------------------------------------------------------------------------
# Regex fallback (used when no API key is present)
# ---------------------------------------------------------------------------

_ALIASES: dict[str, str] = {
    "zin": "Zinfandel", "zinfandel": "Zinfandel",
    "petite sirah": "Petite Sirah", "petite syrah": "Petite Sirah", "durif": "Petite Sirah",
    "grenache": "Grenache", "mourvèdre": "Mourvèdre", "mourvedre": "Mourvèdre",
    "mataro": "Mourvèdre", "monastrell": "Mourvèdre",
    "carignan": "Carignan", "carignane": "Carignan",
    "alicante bouschet": "Alicante Bouschet", "alicante bouchet": "Alicante Bouschet",
    "cinsaut": "Cinsaut", "cinsault": "Cinsaut",
    "syrah": "Syrah", "shiraz": "Syrah",
    "cabernet sauvignon": "Cabernet Sauvignon",
    "cabernet franc": "Cabernet Franc",
    "merlot": "Merlot", "pinot noir": "Pinot Noir", "chardonnay": "Chardonnay",
    "sauvignon blanc": "Sauvignon Blanc", "viognier": "Viognier",
    "roussanne": "Roussanne", "marsanne": "Marsanne",
    "chenin blanc": "Chenin Blanc", "colombard": "Colombard",
    "palomino": "Palomino", "muscat blanc": "Muscat Blanc",
    "muscat noir": "Muscat Noir", "muscat": "Muscat",
    "mission": "Mission", "tempranillo": "Tempranillo",
    "barbera": "Barbera", "sangiovese": "Sangiovese", "nebbiolo": "Nebbiolo",
    "peloursin": "Peloursin", "teroldego": "Teroldego", "refosco": "Refosco",
    "abouriou": "Abouriou", "grand noir": "Grand Noir", "negrette": "Negrette",
    "trousseau": "Trousseau", "bastardo": "Trousseau",
    "tannat": "Tannat", "plavac mali": "Plavac Mali",
    "graciano": "Graciano", "gamay noir": "Gamay Noir", "gamay": "Gamay",
    "gewurztraminer": "Gewürztraminer", "gewürztraminer": "Gewürztraminer",
    "riesling": "Riesling", "flame tokay": "Flame Tokay",
    "mixed black": "Mixed Black (field blend)",
    "golden chasselas": "Golden Chasselas", "chasselas": "Chasselas",
    "valdiguie": "Valdiguié", "mondeuse": "Mondeuse",
    "vermentino": "Vermentino", "rolle": "Vermentino",
    "primitivo": "Primitivo", "monbadon": "Monbadon",
    "béclan": "Béclan", "beclan": "Béclan", "cinsaut": "Cinsaut",
}
_SORTED_ALIASES = sorted(_ALIASES.keys(), key=len, reverse=True)

_CAP_WORD   = r'[A-ZÁÉÍÓÚÀÂÊÎÔÙÛÄËÏÖÜÇÑÈÆŒ][A-Za-záéíóúàâêîôùûäëïöüçñèæœ]+'
_CAP_PHRASE = rf'{_CAP_WORD}(?:\s+{_CAP_WORD}){{0,3}}'
_PAT_A = re.compile(rf'({_CAP_PHRASE})\s*\(\s*(>?~?[\d]+(?:\.\d+)?)\s*%\)', re.UNICODE)
_PAT_B = re.compile(rf'\b(>?~?[\d]+(?:\.\d+)?)\s*%\s+({_CAP_PHRASE})', re.UNICODE)
_PAT_C = re.compile(
    rf'({_CAP_PHRASE})\s+as\s+the\s+\w+(?:\s+\w+)?\s*\(\s*(>?~?[\d]+(?:\.\d+)?)\s*%\)',
    re.UNICODE
)
_PAT_B_OV = re.compile(rf'\b([\d]+(?:\.\d+)?)\s*%\s+[Oo]ld[\s\-]?[Vv]ine\s+({_CAP_PHRASE})', re.UNICODE)
_DOM_PATS  = [re.compile(rf'\b{kw}\s+({_CAP_PHRASE})', re.UNICODE)
              for kw in ('predominantly','primarily','mostly','mainly',
                         'pure','effectively 100%','100%')]
_PAT_HELENA = re.compile(r'\bvariety\s+called\s+Helena\b|\bHelena\s+\(a\s+white\b', re.IGNORECASE)


def _validate(raw: str) -> str | None:
    k = raw.strip().lower()
    canon = _ALIASES.get(k)
    if canon:
        return canon
    if k in {v.lower() for v in _ALIASES.values()}:
        return raw.strip().title()
    return None


def extract_with_regex(vineyard: dict) -> dict:
    """Lightweight regex fallback for when no API key is available."""
    desc = vineyard.get("description", "").strip()
    if not desc:
        return {"varieties": [], "notes": "no description"}

    seen: set[str] = set()
    pct_vars: list[dict] = []

    def _add(raw_name: str, raw_pct: str) -> None:
        canon = _validate(raw_name)
        if not canon:
            return
        key = canon.lower()
        if key in seen:
            return
        seen.add(key)
        s = raw_pct.strip().lstrip(">~≥").strip()
        try:
            pct = float(s)
        except ValueError:
            pct = None
        pct_vars.append({"name": canon, "pct": pct, "inferred": False})

    for m in _PAT_C.finditer(desc):  _add(m.group(1), m.group(2))
    for m in _PAT_A.finditer(desc):  _add(m.group(1), m.group(2))
    for m in _PAT_B_OV.finditer(desc): _add(m.group(2), m.group(1))
    for m in _PAT_B.finditer(desc):  _add(m.group(2), m.group(1))

    dominant = None
    for pat in _DOM_PATS:
        m = pat.search(desc)
        if m:
            dominant = _validate(m.group(1))
            if dominant:
                break

    text_lower = desc.lower()
    all_named: list[str] = []
    named_seen: set[str] = set()
    for alias in _SORTED_ALIASES:
        idx = text_lower.find(alias)
        while idx != -1:
            before_ok = idx == 0 or not text_lower[idx - 1].isalpha()
            end = idx + len(alias)
            after_ok  = end >= len(text_lower) or not text_lower[end].isalpha()
            if before_ok and after_ok:
                canon = _ALIASES[alias]
                if canon.lower() not in named_seen:
                    named_seen.add(canon.lower())
                    all_named.append(canon)
                break
            idx = text_lower.find(alias, idx + 1)
    if _PAT_HELENA.search(desc) and "helena" not in named_seen:
        all_named.append("Helena")

    notes = None
    if pct_vars:
        stated_sum = sum(v["pct"] for v in pct_vars if v["pct"] is not None)
        pct_names  = {v["name"].lower() for v in pct_vars}
        if dominant and dominant.lower() not in pct_names and stated_sum <= 99.0:
            inferred = round(100.0 - stated_sum, 1)
            pct_vars.insert(0, {"name": dominant, "pct": inferred, "inferred": True})
            pct_names.add(dominant.lower())
            notes = f"{dominant} inferred as 100 − {stated_sum:.1f} = {inferred:.1f}%"
        elif stated_sum < 99.0:
            notes = f"Stated percentages sum to {stated_sum:.1f}%; remainder unattributed"
        for var in all_named:
            if var.lower() not in pct_names:
                pct_vars.append({"name": var, "pct": None, "inferred": False})
        return {"varieties": pct_vars, "notes": notes}

    if all_named:
        if re.search(r'\beffectively\s+100%', desc, re.IGNORECASE) and dominant:
            others = [v for v in all_named if v.lower() != dominant.lower()]
            varieties = [{"name": dominant, "pct": 100.0, "inferred": False}] + \
                        [{"name": v, "pct": None, "inferred": False} for v in others]
        else:
            if dominant and dominant in all_named:
                ordered = [dominant] + [v for v in all_named if v.lower() != dominant.lower()]
            else:
                ordered = all_named
            varieties = [{"name": v, "pct": None, "inferred": False} for v in ordered]
        return {"varieties": varieties, "notes": notes}

    return {"varieties": [], "notes": "no varieties identified"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    use_claude = bool(api_key)

    if use_claude:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        print("Using Claude API (claude-haiku-4-5) for extraction.")
    else:
        print("ANTHROPIC_API_KEY not set — using regex fallback.")
        print("For best results, set ANTHROPIC_API_KEY and re-run.\n")

    with open(INPUT_FILE) as f:
        vineyards = json.load(f)

    # Resume support: load existing results
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            results = json.load(f)
        done = {r["name"] for r in results}
        print(f"Resuming — {len(results)} already done, {len(vineyards) - len(done)} remaining.\n")
    else:
        results = []
        done = set()

    total = len(vineyards)
    for i, vineyard in enumerate(vineyards):
        name = vineyard.get("name", "")
        if name in done:
            continue

        print(f"[{i+1}/{total}] {name}")

        if use_claude:
            extraction = extract_with_claude(client, vineyard)
            time.sleep(0.15)   # polite rate-limit pause
        else:
            extraction = extract_with_regex(vineyard)

        results.append({
            "name":      name,
            "url":       vineyard.get("url", ""),
            "AVA":       vineyard.get("AVA", ""),
            "Decade":    vineyard.get("Decade", ""),
            "County":    vineyard.get("County", ""),
            "varieties": extraction.get("varieties", []),
            "notes":     extraction.get("notes"),
        })

        # Save after every vineyard so we can resume safely on interruption
        with open(OUTPUT_FILE, "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    method = "Claude API" if use_claude else "regex fallback"
    print(f"\nDone ({method}). {len(results)} vineyards written to {OUTPUT_FILE}\n")

    # Summary
    variety_counts: dict[str, int] = {}
    pct_count = no_var_count = 0
    for r in results:
        vars_ = r.get("varieties", [])
        if not vars_:
            no_var_count += 1
            continue
        if any(v["pct"] is not None for v in vars_):
            pct_count += 1
        for v in vars_:
            variety_counts[v["name"]] = variety_counts.get(v["name"], 0) + 1

    print(f"Vineyards with ≥1 variety:            {len(results) - no_var_count}")
    print(f"Vineyards with explicit/inferred %:   {pct_count}")
    print(f"Vineyards with no varieties found:    {no_var_count}\n")
    print("Top 40 varieties (by number of vineyards):")
    for vname, cnt in sorted(variety_counts.items(), key=lambda x: -x[1])[:40]:
        print(f"  {cnt:3d}  {vname}")


if __name__ == "__main__":
    main()
