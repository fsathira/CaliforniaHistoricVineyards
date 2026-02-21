"""
main.py
-------
Orchestrates the full pipeline:

  1. Scrape  – fetch all vineyard pages from historicvineyardsociety.org
  2. Analyse – extract grape varieties (with %) and soil types from text
  3. Visualise – generate pie charts and stacked bar charts

Usage
-----
  # Full pipeline (requires internet access):
  python main.py

  # Skip scraping; use bundled sample data:
  python main.py --sample

  # Use previously scraped data:
  python main.py --input data/vineyards_raw.json

  # Change output directory:
  python main.py --sample --output-dir results/

Options
-------
  --sample          Use sample_data.json instead of scraping
  --input FILE      Load raw JSON from FILE (skip scraping)
  --output-dir DIR  Write all output here (default: output/)
  --delay SECS      Seconds between HTTP requests (default: 2.0)
  --min-pct PCT     Min variety % to show individually (default: 3.0)
  --no-interactive  Skip the Plotly HTML chart
"""

import argparse
import json
import logging
import os
import sys

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Scrape and analyse California historic vineyard data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    src = p.add_mutually_exclusive_group()
    src.add_argument("--sample", action="store_true",
                     help="Use bundled sample_data.json (no network needed)")
    src.add_argument("--input", metavar="FILE",
                     help="Load from an existing raw JSON file")

    p.add_argument("--output-dir", default="output", metavar="DIR")
    p.add_argument("--delay", type=float, default=2.0,
                   help="Seconds between HTTP requests (default: 2.0)")
    p.add_argument("--min-pct", type=float, default=3.0,
                   help="Min %% to show a variety individually (default: 3.0)")
    p.add_argument("--no-interactive", action="store_true",
                   help="Skip Plotly HTML chart")
    return p.parse_args()


def load_records(args: argparse.Namespace):
    if args.sample:
        sample_path = os.path.join(os.path.dirname(__file__), "sample_data.json")
        log.info("Loading sample data from %s", sample_path)
        with open(sample_path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    if args.input:
        log.info("Loading raw data from %s", args.input)
        with open(args.input, "r", encoding="utf-8") as fh:
            return json.load(fh)

    # Live scrape
    from scraper import VineyardScraper
    log.info("Scraping historicvineyardsociety.org (delay=%.1fs) …", args.delay)
    scraper = VineyardScraper(delay=args.delay)
    records = scraper.scrape_all()
    if not records:
        log.error("Scraper returned no records. Aborting.")
        sys.exit(1)

    raw_path = os.path.join(args.output_dir, "vineyards_raw.json")
    os.makedirs(args.output_dir, exist_ok=True)
    with open(raw_path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)
    log.info("Raw data saved → %s", raw_path)
    return records


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    # ── Step 1: Load / scrape ────────────────────────────────────────────
    records = load_records(args)
    log.info("Loaded %d vineyard records", len(records))

    # ── Step 2: Analyse ──────────────────────────────────────────────────
    from analyzer import analyse_all
    log.info("Analysing grape varieties and soil types …")
    df = analyse_all(records)

    csv_path = os.path.join(args.output_dir, "vineyards_analysed.csv")
    df.to_csv(csv_path, index=False)
    log.info("Analysis saved → %s", csv_path)

    # Print a readable summary
    print("\n" + "=" * 70)
    print(f"  Historic Vineyard Society – Analysis Summary ({len(df)} vineyards)")
    print("=" * 70)
    for _, row in df.iterrows():
        print(f"\n  {row['name']}")
        if row.get("ava"):
            print(f"    AVA        : {row['ava']}")
        if row.get("county"):
            print(f"    County     : {row['county']}")
        if row.get("decade"):
            print(f"    Decade     : {row['decade']}")
        if row.get("ttb_variety"):
            print(f"    TTB Variety: {row['ttb_variety']} (≥75 %)")
        if row.get("soil_types"):
            print(f"    Soils      : {row['soil_types']}")

        try:
            varieties = json.loads(row.get("varieties_json", "{}"))
        except Exception:
            varieties = {}
        known = {k: v for k, v in varieties.items() if v is not None and v > 0}
        known_sorted = sorted(known.items(), key=lambda x: x[1], reverse=True)
        if known_sorted:
            var_str = ", ".join(f"{v}: {p:.1f}%" for v, p in known_sorted[:6])
            if len(known_sorted) > 6:
                var_str += ", …"
            print(f"    Varieties  : {var_str}")
    print()

    # ── Step 3: Visualise ────────────────────────────────────────────────
    from visualizer import plot_all_pies, plot_stacked_bar, plot_interactive_bar

    log.info("Generating charts …")

    pie_path = os.path.join(args.output_dir, "pies_grid.png")
    plot_all_pies(df, output_path=pie_path, min_pct=args.min_pct)

    bar_path = os.path.join(args.output_dir, "stacked_bar.png")
    plot_stacked_bar(df, output_path=bar_path, min_pct=args.min_pct)

    if not args.no_interactive:
        html_path = os.path.join(args.output_dir, "interactive_bar.html")
        plot_interactive_bar(df, output_path=html_path, min_pct=args.min_pct)

    print(f"\nAll outputs written to: {os.path.abspath(args.output_dir)}/")
    print(f"  {os.path.basename(csv_path)}        – analysis data")
    print(f"  {os.path.basename(pie_path)}         – pie-chart grid (PNG)")
    print(f"  {os.path.basename(bar_path)}      – stacked bar chart (PNG)")
    if not args.no_interactive:
        print(f"  interactive_bar.html  – interactive chart (open in browser)")
    print()


if __name__ == "__main__":
    main()
