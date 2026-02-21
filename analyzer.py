"""
analyzer.py
-----------
Extracts structured insights from raw vineyard text:

  1. Grape varieties  – with percentages where stated
  2. Soil types       – keyword-matched from description text

TTB rule (27 CFR 4.23): a varietal label requires ≥ 75 % of that variety.
We apply this to decide whether to report a single "dominant" variety or
the full breakdown.
"""

import re
import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Comprehensive grape variety list (California-relevant, case-normalised)
# ---------------------------------------------------------------------------
# Ordered longest-first so multi-word varieties match before their components.

KNOWN_VARIETIES: List[str] = [
    # ── Multi-word reds ──────────────────────────────────────────────────
    "Alicante Bouschet",
    "Cabernet Sauvignon",
    "Petite Sirah",
    "Petite Syrah",
    "Plavac Mali",
    "Muscat Noir",
    "Malvasia Nera",
    "Nero d'Avola",
    "Pinot Noir",
    "Pinot Meunier",
    "Trousseau Gris",
    "Crljenak Kaštelanski",
    # ── Single-word reds ─────────────────────────────────────────────────
    "Zinfandel",
    "Primitivo",
    "Carignan",
    "Cariñena",
    "Grenache",
    "Syrah",
    "Shiraz",
    "Mourvedre",
    "Mourvèdre",
    "Cinsaut",
    "Cinsault",
    "Peloursin",
    "Trousseau",
    "Bastardo",
    "Barbera",
    "Sangiovese",
    "Merlot",
    "Tempranillo",
    "Dolcetto",
    "Nebbiolo",
    "Tannat",
    "Negrette",
    "Monbadon",
    "Béclan",
    "Beclan",
    "Graciano",
    "Gamay",
    "Valdiguie",
    "Durif",
    "Teroldego",
    "Refosco",
    "Lagrein",
    "Poulsard",
    "Sagrantino",
    "Aglianico",
    "Montepulciano",
    "Counoise",
    "Corvina",
    "Rondinella",
    "Molinara",
    # ── Multi-word whites ────────────────────────────────────────────────
    "Sauvignon Blanc",
    "Chenin Blanc",
    "Grenache Blanc",
    "Pinot Gris",
    "Pinot Grigio",
    "Pinot Blanc",
    "Muscat Blanc",
    "Orange Muscat",
    "Muscat of Alexandria",
    "Golden Chasselas",
    "Ugni Blanc",
    # ── Single-word whites ───────────────────────────────────────────────
    "Chardonnay",
    "Riesling",
    "Viognier",
    "Roussanne",
    "Marsanne",
    "Clairette",
    "Palomino",
    "Colombard",
    "Burger",
    "Gewürztraminer",
    "Albarino",
    "Albariño",
    "Vermentino",
    "Arneis",
    "Cortese",
    "Fiano",
    "Falanghina",
    "Garganega",
    "Trebbiano",
    "Kerner",
    "Auxerrois",
    "Tocai",
]

# Build a regex alternation sorted by descending length for greedy matching
_VARIETY_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(v) for v in sorted(KNOWN_VARIETIES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Soil keyword taxonomy
# ---------------------------------------------------------------------------

SOIL_TAXONOMY: Dict[str, List[str]] = {
    "Clay":              ["clay", "red clay", "blue clay", "clay pan", "clay-rich"],
    "Clay Loam":         ["clay loam"],
    "Sandy Loam":        ["sandy loam"],
    "Loam":              ["loam", "loamy"],
    "Sand":              ["sand", "sandy", "fine sand", "coarse sand"],
    "Gravel":            ["gravel", "gravelly", "cobble", "cobbles", "cobblestone"],
    "Rocky":             ["rock", "rocky", "stones", "stony"],
    "Volcanic":          ["volcanic", "basalt", "basaltic", "pumice", "tuff", "obsidian"],
    "Alluvial":          ["alluvial", "alluvium", "flood plain", "river deposit"],
    "Limestone":         ["limestone", "calcareous", "chalk", "chalky"],
    "Shale":             ["shale", "shaly"],
    "Decomposed Granite":["decomposed granite", "d.g.", " dg "],
    "Sandstone":         ["sandstone"],
    "Schist":            ["schist", "schistous"],
    "Benchland":         ["benchland", "bench", "hillside", "hillslope", "slope"],
}

# ---------------------------------------------------------------------------
# Helper regex patterns for percentage extraction
# ---------------------------------------------------------------------------

# "78% Zinfandel"  or  "78.5% Zinfandel"
_PCT_BEFORE = re.compile(
    r"(\d+(?:\.\d+)?)\s*%\s*(" +
    "|".join(re.escape(v) for v in sorted(KNOWN_VARIETIES, key=len, reverse=True)) +
    r")\b",
    re.IGNORECASE,
)

# "Zinfandel (78%)"
_PCT_AFTER = re.compile(
    r"\b(" +
    "|".join(re.escape(v) for v in sorted(KNOWN_VARIETIES, key=len, reverse=True)) +
    r")\s*\((\d+(?:\.\d+)?)\s*%\)",
    re.IGNORECASE,
)

# "Zinfandel at 78%"  or  "Zinfandel at approximately 80%"
_QUALIFIER = r"(?:approximately|about|roughly|around|nearly|nearly|~)?\s*"
_PCT_AT = re.compile(
    r"\b(" +
    "|".join(re.escape(v) for v in sorted(KNOWN_VARIETIES, key=len, reverse=True)) +
    r")\s+at\s+" + _QUALIFIER + r"(\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)

# "predominantly Zinfandel at approximately 80%"
_PCT_PREDOMINANTLY = re.compile(
    r"(?:predominantly|primarily|mainly|mostly|largely)\s+(" +
    "|".join(re.escape(v) for v in sorted(KNOWN_VARIETIES, key=len, reverse=True)) +
    r")\s+(?:at\s+)?" + _QUALIFIER + r"(\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)

# "remaining X% includes A, B, and C"  or  "other varieties (X%) including A, B"
_REMAINING = re.compile(
    r"(?:remaining|other\s+varieties?)\s+(?:\()?(\d+(?:\.\d+)?)\s*%\s*(?:\))?\s*"
    r"(?:includes?|is|are|including|:)?\s*(.*?)(?=\.|$)",
    re.IGNORECASE | re.DOTALL,
)


# ---------------------------------------------------------------------------
# Normalise variety name
# ---------------------------------------------------------------------------

def _normalise_variety(name: str) -> str:
    """Return a consistent canonical name for a grape variety."""
    synonyms = {
        "petite syrah": "Petite Sirah",
        "syrah": "Syrah",
        "mourvedre": "Mourvèdre",
        "cinsault": "Cinsaut",
        "bastardo": "Trousseau",   # Trousseau (Bastardo) is the same grape
        "beclan": "Béclan",
        "albarino": "Albariño",
        "carignane": "Carignan",   # Carignane is the older American spelling
    }
    return synonyms.get(name.strip().lower(), name.strip().title())


# ---------------------------------------------------------------------------
# Main extraction functions
# ---------------------------------------------------------------------------

def extract_grape_varieties(text: str) -> Dict[str, Optional[float]]:
    """
    Parse *text* and return a dict mapping variety name → percentage (or None
    when a variety is mentioned without a percentage).

    Handles:
      • "78% Zinfandel, 11% Alicante Bouschet"
      • "Zinfandel (78%), Petite Sirah (9%)"
      • "Zinfandel at 78%"
      • "remaining 2% includes Carignan, Trousseau, …"
      • Varieties mentioned with no percentage → None
    """
    if not text:
        return {}

    varieties: Dict[str, Optional[float]] = {}

    # ── Pattern 1: "X% Variety" ─────────────────────────────────────────
    for m in _PCT_BEFORE.finditer(text):
        pct = float(m.group(1))
        var = _normalise_variety(m.group(2))
        varieties[var] = pct

    # ── Pattern 2: "Variety (X%)" ────────────────────────────────────────
    for m in _PCT_AFTER.finditer(text):
        var = _normalise_variety(m.group(1))
        pct = float(m.group(2))
        if var not in varieties:
            varieties[var] = pct

    # ── Pattern 3: "Variety at X%"  /  "Variety at approximately X%" ─────
    for m in _PCT_AT.finditer(text):
        var = _normalise_variety(m.group(1))
        pct = float(m.group(2))
        if var not in varieties:
            varieties[var] = pct

    # ── Pattern 3b: "predominantly Variety at X%" ────────────────────────
    for m in _PCT_PREDOMINANTLY.finditer(text):
        var = _normalise_variety(m.group(1))
        pct = float(m.group(2))
        if var not in varieties:
            varieties[var] = pct

    # ── Pattern 4: "remaining X% includes A, B, and C" ───────────────────
    for m in _REMAINING.finditer(text):
        remaining_pct = float(m.group(1))
        rest_text = m.group(2)
        # Extract variety names from the remaining list
        found_in_rest = _VARIETY_PATTERN.findall(rest_text)
        if found_in_rest:
            share = round(remaining_pct / len(found_in_rest), 2)
            for v in found_in_rest:
                norm = _normalise_variety(v)
                if norm not in varieties:
                    varieties[norm] = share

    # ── Fallback: mention-only varieties (no percentage) ─────────────────
    for m in _VARIETY_PATTERN.finditer(text):
        norm = _normalise_variety(m.group(0))
        if norm not in varieties:
            varieties[norm] = None  # mentioned but no explicit %

    return varieties


def extract_soil_types(text: str) -> List[str]:
    """
    Scan *text* for soil-type keywords and return a deduplicated list of
    matched soil-type labels from SOIL_TAXONOMY.
    """
    if not text:
        return []

    text_lower = text.lower()
    found = []
    seen = set()

    for label, keywords in SOIL_TAXONOMY.items():
        for kw in keywords:
            if kw.lower() in text_lower and label not in seen:
                found.append(label)
                seen.add(label)
                break

    return found


# ---------------------------------------------------------------------------
# TTB labelling rule helper
# ---------------------------------------------------------------------------

TTB_THRESHOLD = 75.0  # percent


def apply_ttb_rule(varieties: Dict[str, Optional[float]]) -> Optional[str]:
    """
    Return the dominant variety name if one variety has ≥ 75 % of the blend,
    otherwise return None (indicating a true field blend / no single label).
    """
    for var, pct in varieties.items():
        if pct is not None and pct >= TTB_THRESHOLD:
            return var
    return None


def summarise_varieties(
    varieties: Dict[str, Optional[float]],
    threshold: float = 5.0,
) -> Dict[str, float]:
    """
    Return a simplified dict where:
      • varieties with known pct ≥ *threshold* are kept individually
      • varieties below the threshold are grouped as "Other"
      • varieties with unknown pct are grouped as "Unknown %"

    The returned values sum to ≤ 100 (may be < 100 if total is incomplete).
    """
    above: Dict[str, float] = {}
    other_pct: float = 0.0
    unknown: List[str] = []

    for var, pct in varieties.items():
        if pct is None:
            unknown.append(var)
        elif pct >= threshold:
            above[var] = pct
        else:
            other_pct += pct

    if other_pct > 0:
        above["Other"] = round(other_pct, 2)
    if unknown:
        above[f"Unknown % ({', '.join(unknown)})"] = 0.0  # placeholder for display

    return above


# ---------------------------------------------------------------------------
# Batch analysis
# ---------------------------------------------------------------------------

def analyse_all(records: List[Dict]) -> pd.DataFrame:
    """
    Given a list of raw vineyard record dicts (from the scraper), return a
    DataFrame with one row per vineyard containing:
      name, url, structured fields, soil_types, varieties (JSON), ttb_variety
    """
    import json as _json

    rows = []
    for rec in records:
        # Combine all text fields for analysis
        text_fields = ["description", "Characteristics", "characteristics",
                       "Description", "History", "history", "About", "about",
                       "Vineyard Notes", "notes", "background"]
        full_text = " ".join(
            str(rec.get(f, "") or "") for f in text_fields
        )

        varieties = extract_grape_varieties(full_text)
        soils = extract_soil_types(full_text)
        ttb = apply_ttb_rule(varieties)

        row = {
            "name":        rec.get("name", ""),
            "url":         rec.get("url", ""),
            "ava":         rec.get("AVA", ""),
            "county":      rec.get("County", ""),
            "decade":      rec.get("Decade", ""),
            "sub_appellation": rec.get("Sub-Appellation", ""),
            "current_owner":   rec.get("Current Owner", ""),
            "planted_by":      rec.get("Planted by", ""),
            "wineries":        rec.get("Wineries", ""),
            "historical_producers": rec.get("Historical Producers", ""),
            "raw_text":    full_text[:2000],  # truncated for CSV sanity
            "soil_types":  "; ".join(soils) if soils else "",
            "varieties_json": _json.dumps(varieties, ensure_ascii=False),
            "ttb_variety": ttb or "",
        }
        rows.append(row)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json, sys, os

    src = sys.argv[1] if len(sys.argv) > 1 else "data/vineyards_raw.json"
    if not os.path.exists(src):
        print(f"Input file not found: {src}")
        sys.exit(1)

    with open(src, "r", encoding="utf-8") as fh:
        records = json.load(fh)

    df = analyse_all(records)
    os.makedirs("data", exist_ok=True)
    out = "data/vineyards_analysed.csv"
    df.to_csv(out, index=False)
    print(f"Analysed {len(df)} vineyards → {out}")
    print(df[["name", "ttb_variety", "soil_types"]].to_string())
