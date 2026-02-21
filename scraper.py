"""
scraper.py
----------
Scrapes vineyard data from the Historic Vineyard Society website:
  https://historicvineyardsociety.org/vineyards

For each vineyard it extracts:
  Structured  : AVA, Decade, County, Sub-Appellation, Current Owner,
                Planted by, Wineries, Historical Producers
  Unstructured: Characteristics and Description text blocks

Results are cached on disk so the site is not re-hit on subsequent runs.
"""

import os
import re
import time
import json
import logging
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
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

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE_URL,
}


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
        """
        Parameters
        ----------
        delay      : seconds to wait between page requests (be polite)
        cache_dir  : directory where raw HTML is saved
        max_retries: how many times to retry a failed request
        """
        self.delay = delay
        self.cache_dir = cache_dir
        self.max_retries = max_retries

        os.makedirs(cache_dir, exist_ok=True)

        self.session = requests.Session()
        self.session.headers.update(BROWSER_HEADERS)

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _cache_path(self, url: str) -> str:
        """Return a filesystem-safe cache file path for a given URL."""
        safe = re.sub(r"[^\w\-.]", "_", url.replace("https://", "").replace("http://", ""))
        safe = safe[:200]  # avoid overly long filenames
        return os.path.join(self.cache_dir, safe + ".html")

    def fetch(self, url: str) -> str:
        """
        Return the HTML text of *url*.
        Uses on-disk cache; fetches from the network if not cached.
        Retries with exponential back-off on failure.
        """
        path = self._cache_path(url)
        if os.path.exists(path):
            log.debug("Cache hit: %s", url)
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()

        time.sleep(self.delay)

        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, timeout=30)
                resp.raise_for_status()
                html = resp.text
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(html)
                return html
            except requests.RequestException as exc:
                wait = 2 ** attempt * 2
                log.warning("Attempt %d failed for %s: %s – retrying in %ds", attempt + 1, url, exc, wait)
                if attempt < self.max_retries - 1:
                    time.sleep(wait)
                else:
                    raise RuntimeError(f"Failed to fetch {url} after {self.max_retries} attempts: {exc}") from exc

    # ------------------------------------------------------------------
    # Vineyard URL discovery
    # ------------------------------------------------------------------

    def get_vineyard_urls(self) -> List[str]:
        """
        Scrape the main /vineyards listing page and return all individual
        vineyard detail-page URLs.
        """
        html = self.fetch(VINEYARDS_LIST_URL)
        soup = BeautifulSoup(html, "lxml")

        urls: List[str] = []
        seen: set = set()

        # Strategy 1 – links whose href contains '/vineyards/' but is not
        # the listing page itself.
        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            full = urljoin(BASE_URL, href).rstrip("/")
            if (
                "/vineyards/" in full
                and full not in seen
                and full != VINEYARDS_LIST_URL.rstrip("/")
                and not full.endswith("/vineyards")
            ):
                urls.append(full)
                seen.add(full)

        # Strategy 2 – if the site uses a different URL pattern, look for
        # any link whose text looks like a vineyard name and points to the
        # same domain.
        if not urls:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(strip=True)
                if (
                    text
                    and href.startswith("/")
                    and href not in seen
                    and href != "/vineyards"
                ):
                    full = urljoin(BASE_URL, href).rstrip("/")
                    urls.append(full)
                    seen.add(full)

        log.info("Found %d vineyard URLs", len(urls))
        return urls

    # ------------------------------------------------------------------
    # Structured data extraction
    # ------------------------------------------------------------------

    def _extract_structured(self, soup: BeautifulSoup) -> Dict[str, str]:
        """
        Extract key-value structured data (table rows, definition lists,
        or labelled divs) and normalise the keys against STRUCTURED_FIELDS.
        """
        data: Dict[str, str] = {}

        def store(key: str, value: str) -> None:
            key_clean = key.strip().rstrip(":")
            for field in STRUCTURED_FIELDS:
                if field.lower() == key_clean.lower():
                    data[field] = value.strip()
                    return
            # Keep unexpected fields too (they might be useful)
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

        # --- Inline "Label: value" paragraphs ---
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
        """
        Extract free-text sections (Characteristics, Description, History …).
        Returns a dict where keys are section headings and values are the
        concatenated paragraph text.
        """
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

        # Fallback – dump all substantial paragraphs from the main content area
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

    def scrape_vineyard(self, url: str) -> Dict:
        """Fetch one vineyard page and return a merged structured + unstructured dict."""
        html = self.fetch(url)
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
        Scrape every vineyard listed on the main page.
        Returns a list of record dicts.
        """
        urls = self.get_vineyard_urls()
        if not urls:
            log.error(
                "No vineyard URLs found – the site layout may have changed. "
                "Try inspecting the page source manually."
            )
            return []

        records: List[Dict] = []
        for url in tqdm(urls, desc="Scraping vineyards"):
            try:
                record = self.scrape_vineyard(url)
                records.append(record)
                log.debug("OK: %s", record.get("name", url))
            except Exception as exc:
                log.error("Failed: %s – %s", url, exc)

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
