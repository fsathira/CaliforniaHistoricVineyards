"""
Extract grape varieties (with percentages where stated) from vineyard descriptions.
Uses regex + canonical variety list. Infers dominant-variety % when others sum < 100%.

Key design decisions:
- All multi-word variety patterns require CAPITALIZED continuation words, preventing
  greedy matches like "Grenache with about ten" or "Mourvèdre planted in".
- All extracted names are validated against ALIASES; non-varieties are discarded.
- Handles: "X% Variety", "Variety (X%)", "predominantly X", "effectively 100% X",
  "X as the primary variety (Y%)", "Variety (synonym)", remaining-% lists.
- Avoids false positives from soil/geology percentages (">50% calcium carbonate"),
  organic certification ("100% certified organic"), buyer percentages ("buys 100%"),
  vine-age proportions ("95% of the 8 acres"), etc.
"""

import json
import re

INPUT_FILE  = "output/vineyards_raw.json"
OUTPUT_FILE = "output/vineyard_varieties.json"

# ---------------------------------------------------------------------------
# Canonical variety → alias mapping (lower-case alias → canonical name)
# ---------------------------------------------------------------------------
ALIASES: dict[str, str] = {
    # Zinfandel
    "zin": "Zinfandel", "zinfandel": "Zinfandel", "zins": "Zinfandel",
    "primitivo": "Primitivo",

    # Petite Sirah / Durif
    "petite sirah": "Petite Sirah", "petite syrah": "Petite Sirah",
    "durif": "Petite Sirah",

    # Grenache
    "grenache": "Grenache", "garnacha": "Grenache",
    "grenache noir": "Grenache Noir",

    # Mourvèdre
    "mourvedre": "Mourvèdre", "mourvèdre": "Mourvèdre",
    "monastrell": "Mourvèdre", "mataro": "Mourvèdre",

    # Carignan / Carignane
    "carignan": "Carignan", "carignane": "Carignan", "carignano": "Carignan",

    # Alicante Bouschet
    "alicante bouschet": "Alicante Bouschet",
    "alicante bouchet":  "Alicante Bouschet",
    # "alicante" alone is ambiguous; only match compound form above

    # Cinsaut / Cinsault
    "cinsaut": "Cinsaut", "cinsault": "Cinsaut",

    # Syrah / Shiraz
    "syrah": "Syrah", "shiraz": "Syrah",

    # Cabernet Sauvignon
    "cabernet sauvignon": "Cabernet Sauvignon",
    "cab sauvignon":      "Cabernet Sauvignon",

    # Cabernet Franc
    "cabernet franc": "Cabernet Franc",

    # Merlot
    "merlot": "Merlot",

    # Pinot Noir
    "pinot noir": "Pinot Noir",

    # Chardonnay
    "chardonnay": "Chardonnay",

    # Sauvignon Blanc
    "sauvignon blanc": "Sauvignon Blanc",

    # Viognier
    "viognier": "Viognier",

    # Roussanne
    "roussanne": "Roussanne",

    # Marsanne
    "marsanne": "Marsanne",

    # Chenin Blanc
    "chenin blanc": "Chenin Blanc",

    # Colombard
    "colombard": "Colombard", "french colombard": "Colombard",

    # Palomino
    "palomino": "Palomino",

    # Muscat varieties
    "muscat blanc": "Muscat Blanc", "muscat canelli": "Muscat Blanc",
    "muscat noir":  "Muscat Noir",  "orange muscat":  "Orange Muscat",
    "muscat":       "Muscat",       "moscato":        "Muscat",

    # Mission
    "mission": "Mission",

    # Tempranillo
    "tempranillo": "Tempranillo", "tempranilla": "Tempranillo",

    # Barbera
    "barbera": "Barbera",

    # Sangiovese
    "sangiovese": "Sangiovese",

    # Nebbiolo
    "nebbiolo": "Nebbiolo",

    # Peloursin
    "peloursin": "Peloursin",

    # Teroldego
    "teroldego": "Teroldego",

    # Refosco
    "refosco": "Refosco",

    # Abouriou
    "abouriou": "Abouriou",

    # Grand Noir de la Calmette
    "grand noir": "Grand Noir",

    # Negrette
    "negrette": "Negrette",

    # Trousseau / Bastardo
    "trousseau": "Trousseau", "bastardo": "Trousseau",

    # Tannat
    "tannat": "Tannat",

    # Plavac Mali
    "plavac mali": "Plavac Mali",

    # Monbadon
    "monbadon": "Monbadon",

    # Béclan / Beclan
    "béclan": "Béclan", "beclan": "Béclan",

    # Graciano
    "graciano": "Graciano",

    # Gamay / Gamay Noir
    "gamay noir": "Gamay Noir", "gamay": "Gamay", "napa gamay": "Gamay",

    # Gewürztraminer
    "gewurztraminer": "Gewürztraminer", "gewürztraminer": "Gewürztraminer",

    # Riesling
    "riesling": "Riesling", "johannisberg riesling": "Riesling",

    # Flame Tokay — "tokay" alone omitted: often refers to "Tokay Sandy Loam" soil in Lodi
    "flame tokay": "Flame Tokay",

    # Mixed black (field blend)
    "mixed black": "Mixed Black (field blend)",
    "mixed whites": "Mixed Whites (field blend)",

    # Golden Chasselas
    "golden chasselas": "Golden Chasselas", "chasselas": "Chasselas",

    # Helena (white cross – very rare; only matched as explicit named variety)
    # NOT added here to avoid matching "St. Helena" place-names;
    # handled separately in extract().

    # Valdiguié
    "valdiguie": "Valdiguié", "valdiguié": "Valdiguié",

    # Mondeuse
    "mondeuse": "Mondeuse",

    # Counoise
    "counoise": "Counoise",

    # Vermentino / Rolle
    "rolle": "Vermentino", "vermentino": "Vermentino",

    # Carménère
    "carmenere": "Carménère", "carménère": "Carménère",
}

# Canonical name set (lower-cased) for validation
CANON_LOWER: set[str] = {v.lower() for v in ALIASES.values()}

# Sort longest-first so multi-word aliases match before single-word ones
SORTED_ALIASES = sorted(ALIASES.keys(), key=len, reverse=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_name(raw: str) -> str | None:
    """
    Return canonical variety name for raw string, or None if not a known variety.
    """
    key = raw.strip().lower()
    direct = ALIASES.get(key)
    if direct:
        return direct
    # Check if already matches a canonical name
    if key in CANON_LOWER:
        return raw.strip().title()
    return None


def parse_pct(s: str) -> float | None:
    s = s.strip().lstrip(">~≥≤≈").strip()
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Capitalized word component (for variety names)
# First word: must start uppercase; subsequent words: also start uppercase.
# This prevents greedily matching "Grenache with about ten" or "Mourvèdre planted in".
_CAP_WORD   = r'[A-ZÁÉÍÓÚÀÂÊÎÔÙÛÄËÏÖÜÇÑÈÆŒÈ][A-Za-záéíóúàâêîôùûäëïöüçñèæœè]+'
_CAP_PHRASE = rf'{_CAP_WORD}(?:\s+{_CAP_WORD}){{0,3}}'

# Pattern A: CapPhrase (X%) — e.g. "Alicante Bouschet (2%)" "Zinfandel (>90%)"
PAT_A = re.compile(
    rf'({_CAP_PHRASE})\s*\(\s*(>?~?[\d]+(?:\.\d+)?)\s*%\)',
    re.UNICODE
)

# Pattern B: X% CapPhrase — e.g. "78% Zinfandel" "roughly 70% Zin"
PAT_B = re.compile(
    rf'\b(>?~?≥?[\d]+(?:\.\d+)?)\s*%\s+({_CAP_PHRASE})',
    re.UNICODE
)

# Pattern C: CapPhrase as the [adj] variety (X%)
#   e.g. "Zinfandel as the primary variety (>90%)"
#   NOTE: no IGNORECASE — prevents matching lowercase context words ("with zinfandel")
#   as part of the variety name.
PAT_C = re.compile(
    rf'({_CAP_PHRASE})\s+as\s+the\s+\w+(?:\s+\w+)?\s*\(\s*(>?~?[\d]+(?:\.\d+)?)\s*%\)',
    re.UNICODE
)

# Pattern B-oldvine: "X% old vine VARIETY" — common agricultural qualifier.
# No IGNORECASE — same reason as PAT_C/_DOM_PATS; use explicit [Oo][Vv] instead.
PAT_B_OLDVINE = re.compile(
    rf'\b([\d]+(?:\.\d+)?)\s*%\s+[Oo]ld[\s\-]?[Vv]ine\s+({_CAP_PHRASE})',
    re.UNICODE
)

# Dominant-language patterns.
# NOTE: no IGNORECASE — _CAP_PHRASE requires uppercase first char, which correctly
# stops matching at lowercase words like "planted" or "in" without IGNORECASE.
# The keywords (predominantly, primarily, etc.) are lowercase in practice.
_DOM_PATS = [
    re.compile(rf'\bpredominantly\s+({_CAP_PHRASE})',      re.UNICODE),
    re.compile(rf'\bprimarily\s+({_CAP_PHRASE})',          re.UNICODE),
    re.compile(rf'\bmostly\s+({_CAP_PHRASE})',             re.UNICODE),
    re.compile(rf'\bmainly\s+({_CAP_PHRASE})',             re.UNICODE),
    re.compile(rf'\bpure\s+({_CAP_PHRASE})',               re.UNICODE),
    re.compile(rf'\beffectively\s+100%\s+({_CAP_PHRASE})', re.UNICODE),
    re.compile(rf'\b100%\s+({_CAP_PHRASE})',               re.UNICODE),
]

# "effectively 100%" — for the pct_vars=[] branch
PAT_EFF100 = re.compile(r'\beffectively\s+100%', re.IGNORECASE)

# "Helena" as an explicit named variety (avoid matching "St. Helena" place names)
PAT_HELENA = re.compile(
    r'\bvariety\s+called\s+Helena\b'
    r'|\bHelena\s+\(a\s+white\b'
    r'|\bHelena\s+grape',
    re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Core extraction functions
# ---------------------------------------------------------------------------

def _validated(raw_name: str) -> str | None:
    """Return canonical name only if it is a known variety, else None."""
    return normalize_name(raw_name)


def extract_pct_blocks(text: str) -> list[dict]:
    """
    Find explicit percentage + variety associations.
    All extracted names are validated against ALIASES.
    Returns list of {"name": canon, "pct": float|None, "inferred": False}
    """
    results: list[dict] = []
    seen: set[str] = set()

    def _add(raw_name: str, raw_pct: str) -> None:
        canon = _validated(raw_name)
        if canon is None:
            return
        pct = parse_pct(raw_pct)
        key = canon.lower()
        if key not in seen:
            seen.add(key)
            results.append({"name": canon, "pct": pct, "inferred": False})

    for m in PAT_C.finditer(text):
        _add(m.group(1), m.group(2))

    for m in PAT_A.finditer(text):
        _add(m.group(1), m.group(2))

    for m in PAT_B_OLDVINE.finditer(text):
        _add(m.group(2), m.group(1))

    for m in PAT_B.finditer(text):
        _add(m.group(2), m.group(1))

    return results


def dominant_from_text(text: str) -> str | None:
    """
    Detect "predominantly X", "primarily X", "effectively 100% X", "100% X", etc.
    Returns canonical variety name or None.
    """
    for pat in _DOM_PATS:
        m = pat.search(text)
        if m:
            canon = _validated(m.group(1))
            if canon:
                return canon
    return None


def find_all_varieties(text: str) -> list[str]:
    """
    Find ALL variety names mentioned in text (regardless of %).
    Returns list of canonical names in order of first appearance.
    """
    found: list[str] = []
    seen:  set[str]  = set()
    text_lower = text.lower()
    for alias in SORTED_ALIASES:
        # Avoid matching sub-strings of longer words by checking word boundaries
        idx = text_lower.find(alias)
        while idx != -1:
            # Check boundaries: char before and after must not be alpha
            before_ok = (idx == 0) or not text_lower[idx - 1].isalpha()
            end = idx + len(alias)
            after_ok  = (end >= len(text_lower)) or not text_lower[end].isalpha()
            if before_ok and after_ok:
                canon = ALIASES[alias]
                if canon.lower() not in seen:
                    seen.add(canon.lower())
                    found.append(canon)
                break
            idx = text_lower.find(alias, idx + 1)

    # Check for "Helena" as an explicitly named variety
    if PAT_HELENA.search(text):
        if "helena" not in seen:
            found.append("Helena")

    return found


# ---------------------------------------------------------------------------
# Per-vineyard extraction
# ---------------------------------------------------------------------------

def extract(vineyard: dict) -> dict:
    name = vineyard.get("name", "")
    desc = vineyard.get("description", "").strip()

    record: dict = {
        "name":      name,
        "url":       vineyard.get("url", ""),
        "AVA":       vineyard.get("AVA", ""),
        "Decade":    vineyard.get("Decade", ""),
        "County":    vineyard.get("County", ""),
        "varieties": [],
        "notes":     None,
    }

    if not desc:
        record["notes"] = "no description"
        return record

    # ------------------------------------------------------------------ #
    # Step 1: extract explicit percentage blocks                          #
    # ------------------------------------------------------------------ #
    pct_vars = extract_pct_blocks(desc)

    # ------------------------------------------------------------------ #
    # Step 2: detect dominant variety language                            #
    # ------------------------------------------------------------------ #
    dominant = dominant_from_text(desc)

    # ------------------------------------------------------------------ #
    # Step 3: find all mentioned variety names                            #
    # ------------------------------------------------------------------ #
    all_named = find_all_varieties(desc)

    # ------------------------------------------------------------------ #
    # Step 4: assemble final variety list                                 #
    # ------------------------------------------------------------------ #
    if pct_vars:
        # --- We have at least some explicit percentages ---
        stated_sum = sum(v["pct"] for v in pct_vars if v["pct"] is not None)
        pct_names  = {v["name"].lower() for v in pct_vars}

        # If there is a dominant variety NOT in the pct list and percentages
        # don't already sum to ~100%, infer its share.
        if dominant and dominant.lower() not in pct_names and stated_sum <= 99.0:
            inferred = round(100.0 - stated_sum, 1)
            pct_vars.insert(0, {"name": dominant, "pct": inferred, "inferred": True})
            record["notes"] = (
                f"{dominant} pct inferred as 100 − {stated_sum:.1f} = {inferred:.1f}%"
            )
            pct_names.add(dominant.lower())
        elif stated_sum < 99.0 and pct_vars:
            record["notes"] = (
                f"Listed percentages sum to {stated_sum:.1f}%; "
                f"remainder not attributed to a specific variety"
            )

        # Append any named varieties not already in the list (pct=null)
        for var in all_named:
            if var.lower() not in pct_names:
                pct_vars.append({"name": var, "pct": None, "inferred": False})
                pct_names.add(var.lower())

        record["varieties"] = pct_vars

    else:
        # --- No explicit percentages found ---

        # "effectively 100% X" → first variety gets 100%
        if dominant and PAT_EFF100.search(desc):
            others = [v for v in all_named if v.lower() != dominant.lower()]
            record["varieties"] = [
                {"name": dominant, "pct": 100.0, "inferred": False}
            ] + [{"name": v, "pct": None, "inferred": False} for v in others]
            return record

        if all_named:
            # Put dominant first if present
            if dominant and dominant in all_named:
                ordered = [dominant] + [v for v in all_named if v.lower() != dominant.lower()]
            else:
                ordered = all_named
            record["varieties"] = [
                {"name": v, "pct": None, "inferred": False} for v in ordered
            ]
        else:
            record["notes"] = "no varieties identified"

    return record


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    with open(INPUT_FILE) as f:
        data = json.load(f)

    results = [extract(v) for v in data]

    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Written {len(results)} records to {OUTPUT_FILE}\n")

    # ---- Summary ----
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
            n = v["name"]
            variety_counts[n] = variety_counts.get(n, 0) + 1

    print(f"Vineyards with ≥1 variety identified: {len(results) - no_var_count}")
    print(f"Vineyards with explicit/inferred %:   {pct_count}")
    print(f"Vineyards with no varieties found:    {no_var_count}\n")
    print("Top 40 varieties (by number of vineyards):")
    for name, cnt in sorted(variety_counts.items(), key=lambda x: -x[1])[:40]:
        print(f"  {cnt:3d}  {name}")


if __name__ == "__main__":
    main()
