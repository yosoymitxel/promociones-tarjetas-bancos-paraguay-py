from __future__ import annotations

import hashlib
import json
import re
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

# Try importing playwright — it's optional for HTTP-only scrapers
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

# Try importing stealth
try:
    from playwright_stealth import stealth_sync
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False


# ─── Realistic browser headers ────────────────────────────────────
STEALTH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-PY,es;q=0.9,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}


class ScraperBase(ABC):
    """Base class for all bank scrapers.

    Each subclass must define class-level attributes and implement
    scrape_api() and scrape_html().  The scrape_playwright() fallback
    uses a generic DOM parser but can be overridden for custom logic.

    Fallback order:  API → HTML → Playwright
    """

    bank_id: str
    bank_name: str
    bank_url: str
    bank_color: str
    bank_short: str

    def __init__(self):
        self.reports_dir = Path("reports") / self.bank_id
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────────
    # Public entry-point with cascading fallback
    # ──────────────────────────────────────────────
    def scrape(self) -> list[dict]:
        methods_tried: list[str] = []

        # 1) API
        try:
            promos = self.scrape_api()
            methods_tried.append("api")
            if promos:
                self._save_report({"method": "api", "count": len(promos), "success": True})
                return promos
        except Exception as e:
            methods_tried.append(f"api:{type(e).__name__}:{e}")

        # 2) HTML (httpx)
        try:
            promos = self.scrape_html()
            methods_tried.append("html")
            if promos:
                self._save_report({"method": "html", "count": len(promos), "success": True})
                return promos
        except Exception as e:
            methods_tried.append(f"html:{type(e).__name__}:{e}")

        # 3) Playwright
        if HAS_PLAYWRIGHT:
            try:
                promos = self.scrape_playwright()
                methods_tried.append("playwright")
                self._save_report({
                    "method": "playwright",
                    "count": len(promos),
                    "success": bool(promos),
                })
                return promos
            except Exception as e:
                methods_tried.append(f"playwright:{type(e).__name__}:{e}")

        # All failed
        self._save_report({
            "method": "all_failed",
            "methods_tried": methods_tried,
            "success": False,
        })
        return []

    # ──────────────────────────────────────────────
    # Abstract methods — must be implemented
    # ──────────────────────────────────────────────
    @abstractmethod
    def scrape_api(self) -> list[dict]:
        """Try fetching from an API endpoint.  Raise NotImplementedError if N/A."""

    @abstractmethod
    def scrape_html(self) -> list[dict]:
        """Fetch raw HTML with httpx and parse with BeautifulSoup."""

    # ──────────────────────────────────────────────
    # Playwright fallback (generic, can be overridden)
    # ──────────────────────────────────────────────
    def scrape_playwright(self, scroll: bool = False) -> list[dict]:
        """Headless Chromium via Playwright.  Override for custom SPA logic."""
        if not HAS_PLAYWRIGHT:
            raise RuntimeError("playwright not installed")

        promos: list[dict] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=STEALTH_HEADERS["User-Agent"],
                locale="es-PY",
                viewport={"width": 1440, "height": 900},
            )
            page = ctx.new_page()
            if HAS_STEALTH:
                stealth_sync(page)
            try:
                page.goto(self.bank_url, wait_until="domcontentloaded", timeout=45_000)

                if scroll:
                    self._scroll_infinite(page)
                else:
                    page.wait_for_timeout(5_000)

                html = page.content()
                self._save_html_sample(html, "playwright")

                soup = BeautifulSoup(html, "html.parser")
                promos = self._parse_common(soup)
            finally:
                browser.close()

        return promos

    # ──────────────────────────────────────────────
    # HTTP helper
    # ──────────────────────────────────────────────
    def fetch_html(self, url: str | None = None, *, timeout: int = 20) -> str:
        """GET a URL with stealth headers and return the response text."""
        url = url or self.bank_url
        with httpx.Client(
            headers=STEALTH_HEADERS,
            follow_redirects=True,
            timeout=timeout,
            verify=False,
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text

    def fetch_json(self, url: str, *, timeout: int = 20) -> dict | list:
        """GET a JSON endpoint and return parsed data."""
        headers = {**STEALTH_HEADERS, "Accept": "application/json"}
        with httpx.Client(
            headers=headers,
            follow_redirects=True,
            timeout=timeout,
            verify=False,
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()

    # ──────────────────────────────────────────────
    # Promo factory
    # ──────────────────────────────────────────────
    def make_promo(
        self,
        title: str,
        desc: str | None = None,
        img: str = "",
        href: str = "",
        category: str | None = None,
    ) -> dict:
        # Resolve relative hrefs
        if href and not href.startswith("http"):
            href = urljoin(self.bank_url, href)

        # Clean description: strip HTML tags, preserve explicit newlines (from <br> or existing)
        if desc is not None:
            # Parse HTML
            soup = BeautifulSoup(desc, "html.parser")
            # Replace <br> tags with newline to preserve explicit line breaks
            for br in soup.find_all("br"):
                br.replace_with("\n")
            # Get text (newline characters from replaced <br> and original text are kept)
            desc = soup.get_text()
            # Strip leading/trailing whitespace
            desc = desc.strip()
            # If after cleaning we have empty string, set to None
            if desc == "":
                desc = None

        # Generate a unique, stable, deterministic ID based on title, description, and link
        unique_payload = f"{self.bank_id}|{title.strip()}"
        if desc:
            unique_payload += f"|{desc.strip()}"
        if href:
            unique_payload += f"|{href.strip()}"
        
        promo_hash = hashlib.md5(unique_payload.encode('utf-8')).hexdigest()[:16]
        promo_id = f"{self.bank_id}-{promo_hash}"

        return {
            "id": promo_id,
            "title": title.strip(),
            "desc": desc,
            "img": img,
            "href": href,
            "bankId": self.bank_id,
            "bankShort": self.bank_short,
            "bankColor": self.bank_color,
            "category": category,
        }

    # ──────────────────────────────────────────────
    # Reports
    # ──────────────────────────────────────────────
    def _save_report(self, data: dict):
        data["timestamp"] = datetime.now().isoformat()
        data["url"] = self.bank_url
        data["bank_id"] = self.bank_id
        report_file = self.reports_dir / f"report_{int(time.time())}.json"
        report_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _save_html_sample(self, html: str, method: str):
        sample_file = self.reports_dir / f"html_{method}_{int(time.time())}.html"
        # Save first 5000 chars for debugging
        sample_file.write_text(html[:5000])

    # ──────────────────────────────────────────────
    # Playwright helpers
    # ──────────────────────────────────────────────
    def _scroll_infinite(self, page, rounds: int = 5, delay: int = 2000):
        """Scroll to bottom repeatedly for infinite-scroll pages."""
        for _ in range(rounds):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(delay)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

    # ──────────────────────────────────────────────
    # Generic DOM parser (used by Playwright fallback)
    # ──────────────────────────────────────────────
    def _parse_common(self, soup: BeautifulSoup) -> list[dict]:
        """Try a series of common CSS selectors to find promo cards."""
        selectors = [
            ".promo-card", ".promocion", '[class*="benefit"]', '[class*="card"]',
            "article", ".item", ".promo", '[class*="promo"]', ".entry",
        ]
        promos: list[dict] = []

        for sel in selectors:
            for el in soup.select(sel)[:40]:
                title_el = el.select_one("h1,h2,h3,h4,h5,.title,.name")
                title = title_el.get_text(strip=True) if title_el else ""
                if title and 3 < len(title) < 200:
                    img = el.select_one("img")
                    img_url = ""
                    if img and img.get("src"):
                        src = img.get("src", "")
                        img_url = src if src.startswith("http") else urljoin(self.bank_url, src)

                    link = el.select_one("a")
                    href = link.get("href", "") if link else ""

                    promos.append(self.make_promo(
                        title=title,
                        desc=el.select_one("p").get_text(strip=True) if el.select_one("p") else None,
                        img=img_url,
                        href=href,
                    ))
            if promos:
                break

        return promos