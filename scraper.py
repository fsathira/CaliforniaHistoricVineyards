"""
scraper.py
----------
Scrapes vineyard data from the Historic Vineyard Society website:
  https://historicvineyardsociety.org/vineyards   (listing – JS-rendered)
  https://historicvineyardsociety.org/vineyard/NAME  (detail pages)

Uses Playwright (headless Chromium) so that JS-rendered content is fully
loaded before parsing.  BeautifulSoup is used for parsing the rendered HTML.

Results are cached on disk so the site is not re-hit on subsequent runs.
"""

import os
import re
import time
import json
import logging
from typing import Dict, List, Optional

from bs4 import BeautifulSoup, Tag
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://historicvineyardsociety.org"
VINEYARDS_LIST_URL = "https://historicvineyardsociety.org/vineyards"
CHROMIUM_BINARY = "/root/.cache/ms-playwright/chromium-1194/chrome-linux/chrome"

STRUCTURED_FIELDS = [
    "AVA",
    "Decade",
    "County",
    "Sub-Appellation",
    "Current Owner",
    "Planted by",
    "Wineries",
    "Historical Producers",
]


# ---------------------------------------------------------------------------
# Playwright helpers
# ---------------------------------------------------------------------------

def _get_chromium_path() -> Optional[str]:
    """Return the path to a usable Chromium binary, or None to let Playwright decide."""
    if os.path.exists(CHROMIUM_BINARY):
        return CHROMIUM_BINARY
    return None


def _fetch_rendered_html(url: str, page, wait_selector: Optional[str] = None) -> str:
    """
    Navigate *page* to *url*, optionally wait for *wait_selector* to appear,
    then return the fully-rendered page HTML.
    """
    page.goto(url, wait_until="networkidle", timeout=60_000)
    if wait_selector:
        try:
            page.wait_for_selector(wait_selector, timeout=15_000)
        except Exception:
            pass  # best-effort; continue with whatever loaded
    return page.content()


# ---------------------------------------------------------------------------
# Scraper class
# ---------------------------------------------------------------------------

class VineyardScraper:
    """Scrapes all vineyard pages from the Historic Vineyard Society website."""

    def __init__(
        self,
        delay: float = 2.0,
        cache_dir: str = "cache",
        max_retries: int = 3,
    ):
        self.delay = delay
        self.cache_dir = cache_dir
        self.max_retries = max_retries
        os.makedirs(cache_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_path(self, url: str) -> str:
        safe = re.sub(r"[^\w\-.]", "_", url.replace("https://", "").replace("http://", ""))
        safe = safe[:200]
        return os.path.join(self.cache_dir, safe + ".html")

    def _load_cache(self, url: str) -> Optional[str]:
        path = self._cache_path(url)
        if os.path.exists(path):
            log.debug("Cache hit: %s", url)
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()
        return None

    def _save_cache(self, url: str, html: str) -> None:
        path = self._cache_path(url)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)

    # ------------------------------------------------------------------
    # Fetch with Playwright (with retry + cache)
    # ------------------------------------------------------------------

    def fetch(self, url: str, page, wait_selector: Optional[str] = None) -> str:
        """Return rendered HTML for *url*, using cache when available."""
        cached = self._load_cache(url)
        if cached:
            return cached

        time.sleep(self.delay)

        for attempt in range(self.max_retries):
            try:
                html = _fetch_rendered_html(url, page, wait_selector)
                self._save_cache(url, html)
                return html
            except Exception as exc:
                wait = 2 ** attempt * 2
                log.warning(
                    "Attempt %d failed for %s: %s – retrying in %ds",
                    attempt + 1, url, exc, wait,
                )
                if attempt < self.max_retries - 1:
                    time.sleep(wait)
                else:
                    raise RuntimeError(
                        f"Failed to fetch {url} after {self.max_retries} attempts: {exc}"
                    ) from exc

    # ------------------------------------------------------------------
    # Vineyard URL discovery
    # ------------------------------------------------------------------

    def get_vineyard_urls(self, page) -> List[str]:
        """
        Scrape the JS-rendered /vineyards listing page and return all
        individual vineyard detail-page URLs (/vineyard/<name>).
        """
        html = self.fetch(VINEYARDS_LIST_URL, page)
        soup = BeautifulSoup(html, "lxml")

        urls: List[str] = []
        seen: set = set()

        # The detail pages live under /vineyard/ (singular)
        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            # Normalise to absolute URL
            if href.startswith("http"):
                full = href.rstrip("/")
            elif href.startswith("/"):
                full = (BASE_URL + href).rstrip("/")
            else:
                continue

            # Must be a detail page: /vineyard/<something>
            if re.search(r"/vineyard/[^/]+$", full) and full not in seen:
                urls.append(full)
                seen.add(full)

        log.info("Found %d vineyard URLs on listing page", len(urls))
        return urls

    # ------------------------------------------------------------------
    # Structured data extraction
    # ------------------------------------------------------------------

    def _extract_structured(self, soup: BeautifulSoup) -> Dict[str, str]:
        data: Dict[str, str] = {}

        def store(key: str, value: str) -> None:
            key_clean = key.strip().rstrip(":")
            for field in STRUCTURED_FIELDS:
                if field.lower() == key_clean.lower():
                    data[field] = value.strip()
                    return
            data[key_clean] = value.strip()

        # --- HTML <table> ---
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all(["th", "td"])
                if len(cells) >= 2:
                    store(cells[0].get_text(), cells[1].get_text())

        # --- <dl>/<dt>/<dd> pairs ---
        for dl in soup.find_all("dl"):
            dts = dl.find_all("dt")
            dds = dl.find_all("dd")
            for dt, dd in zip(dts, dds):
                store(dt.get_text(), dd.get_text())

        # --- Elements with class names hinting at key-value pairs ---
        # e.g. <div class="field--label">AVA</div><div class="field--item">...</div>
        for label_el in soup.find_all(class_=re.compile(r"field[-_]label|label|meta[-_]label", re.I)):
            label_text = label_el.get_text(strip=True)
            # Try the immediately following sibling with a "value"-ish class
            value_el = label_el.find_next_sibling(
                class_=re.compile(r"field[-_](item|value)|value|meta[-_]value", re.I)
            )
            if not value_el:
                # Or a following element at the same level
                value_el = label_el.find_next_sibling()
            if value_el:
                store(label_text, value_el.get_text(separator=", ", strip=True))

        # --- Inline "Label: value" paragraphs / spans ---
        if len(data) < 2:
            for tag in soup.find_all(["p", "div", "li", "span"]):
                text = tag.get_text(separator=" ", strip=True)
                for field in STRUCTURED_FIELDS:
                    if field.lower() in text.lower() and ":" in text:
                        m = re.search(
                            rf"{re.escape(field)}\s*:\s*(.+?)(?:\n|$)",
                            text,
                            re.IGNORECASE,
                        )
                        if m and field not in data:
                            data[field] = m.group(1).strip()

        return data

    # ------------------------------------------------------------------
    # Unstructured data extraction
    # ------------------------------------------------------------------

    def _extract_unstructured(self, soup: BeautifulSoup) -> Dict[str, str]:
        data: Dict[str, str] = {}

        SECTION_KEYWORDS = [
            "characteristics", "description", "history", "about",
            "vineyard notes", "notes", "background", "overview",
        ]

        def paragraphs_after(heading_tag: Tag) -> str:
            parts = []
            for sib in heading_tag.find_next_siblings():
                if sib.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    break
                if isinstance(sib, Tag):
                    text = sib.get_text(separator=" ", strip=True)
                    if text:
                        parts.append(text)
            return " ".join(parts)

        for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            h_text = heading.get_text(strip=True).lower()
            if any(kw in h_text for kw in SECTION_KEYWORDS):
                section_name = heading.get_text(strip=True)
                content = paragraphs_after(heading)
                if content:
                    data[section_name] = content

        # Fallback – collect all substantial paragraphs from the main content area
        if not data:
            main = (
                soup.find("main")
                or soup.find("article")
                or soup.find(class_=re.compile(r"entry.content|post.content|page.content", re.I))
                or soup.find(class_=re.compile(r"content|entry|post|body", re.I))
            )
            container = main or soup.body or soup
            paragraphs = [
                p.get_text(separator=" ", strip=True)
                for p in container.find_all("p")
                if len(p.get_text(strip=True)) > 60
            ]
            if paragraphs:
                data["description"] = " ".join(paragraphs)

        return data

    # ------------------------------------------------------------------
    # Single vineyard scrape
    # ------------------------------------------------------------------

    def scrape_vineyard(self, url: str, page) -> Dict:
        """Fetch one vineyard detail page and return a merged data dict."""
        html = self.fetch(url, page)
        soup = BeautifulSoup(html, "lxml")

        # Vineyard name
        name = ""
        h1 = soup.find("h1")
        if h1:
            name = h1.get_text(strip=True)
        elif soup.title:
            name = soup.title.get_text(strip=True).split("|")[0].strip()

        structured = self._extract_structured(soup)
        unstructured = self._extract_unstructured(soup)

        return {
            "name": name,
            "url": url,
            **{f: structured.get(f, "") for f in STRUCTURED_FIELDS},
            **unstructured,
        }

    # ------------------------------------------------------------------
    # Scrape all vineyards
    # ------------------------------------------------------------------

    def scrape_all(self) -> List[Dict]:
        """
        Launch a headless browser, discover all vineyard URLs from the
        listing page, then scrape each detail page.
        Returns a list of record dicts.
        """
        from playwright.sync_api import sync_playwright

        chromium_path = _get_chromium_path()

        with sync_playwright() as pw:
            launch_kwargs: Dict = {
                "headless": True,
                "args": [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            }
            if chromium_path:
                launch_kwargs["executable_path"] = chromium_path

            browser = pw.chromium.launch(**launch_kwargs)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/141.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()

            try:
                urls = self.get_vineyard_urls(page)
            except Exception as exc:
                log.error("Could not fetch vineyard listing: %s", exc)
                browser.close()
                return []

            if not urls:
                log.error(
                    "No vineyard URLs found – the site layout may have changed. "
                    "Try inspecting the page source manually."
                )
                browser.close()
                return []

            records: List[Dict] = []
            for url in tqdm(urls, desc="Scraping vineyards"):
                try:
                    record = self.scrape_vineyard(url, page)
                    records.append(record)
                    log.debug("OK: %s", record.get("name", url))
                except Exception as exc:
                    log.error("Failed: %s – %s", url, exc)

            browser.close()

        log.info("Scraped %d vineyards", len(records))
        return records


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------

def save_json(records: List[Dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)
    log.info("Saved %d records to %s", len(records), path)


if __name__ == "__main__":
    scraper = VineyardScraper(delay=2.0)
    data = scraper.scrape_all()
    os.makedirs("data", exist_ok=True)
    save_json(data, "data/vineyards_raw.json")
    print(f"Done. {len(data)} vineyards saved to data/vineyards_raw.json")
