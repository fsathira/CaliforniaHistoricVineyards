# California Historic Vineyards

A data pipeline that scrapes the [Historic Vineyard Society](https://historicvineyardsociety.org/vineyards) website, analyzes grape variety composition and soil types across California's historic vineyards, and generates an interactive HTML analytics report.

## Output

A pre-built report is available at `output/index.html` — open it in any browser without running anything.

## Pipeline Overview

```
scraper.py   →  vineyards_raw.json
analyzer.py  →  vineyards_analysed.csv / vineyard_varieties.json
visualizer.py→  pies_grid.png / stacked_bar.png / interactive_bar.html
build_report.py → output/index.html
```

`main.py` orchestrates steps 1–3. `build_report.py` runs step 4 independently.

## Dependencies

Requires **Python 3.8+**.

```bash
pip install -r requirements.txt
playwright install chromium   # downloads the headless browser
```

Key packages:
- `playwright` — headless Chromium for scraping JS-rendered pages
- `beautifulsoup4` / `lxml` — HTML parsing
- `pandas` — data wrangling
- `matplotlib` / `seaborn` — static charts
- `plotly` — interactive charts

## Usage

### Full pipeline (scrapes live site)

```bash
python3 main.py
```

### Skip scraping — use bundled sample data

```bash
python3 main.py --sample
```

### Use previously scraped data

```bash
python3 main.py --input output/vineyards_raw.json
```

### Rebuild the HTML report from existing analysis output

```bash
python3 build_report.py
```

### Options for `main.py`

| Flag | Default | Description |
|------|---------|-------------|
| `--sample` | — | Use `sample_data.json` instead of scraping |
| `--input FILE` | — | Load raw JSON from FILE, skip scraping |
| `--output-dir DIR` | `output/` | Directory for all generated files |
| `--delay SECS` | `2.0` | Seconds between HTTP requests |
| `--min-pct PCT` | `3.0` | Minimum variety % to show individually in charts |

## Exploratory Notebook

`vineyard_analysis.ipynb` contains an exploratory Jupyter notebook.

```bash
jupyter notebook vineyard_analysis.ipynb
```
