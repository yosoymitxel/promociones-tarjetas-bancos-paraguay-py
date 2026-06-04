"""
Base class and shared utilities for all bank scrapers.

Key design decisions
--------------------
- ``requires_playwright``  class attribute (default False) replaces the
  hard-coded list in main.py, so adding a new SPA scraper only requires
  setting the attribute on that class.
- ``open_playwright_page()``  context manager eliminates the ~30-line
  Playwright boilerplate that was copy-pasted in GNB, Continental, Itaú
  and PersonalPay.
- ``_extract_item_fields()`` / ``_parse_api_items()``  replace five near-
  identical field-extraction loops spread across scrape_api() methods.
- ``_promos_from_intercepted()``  turns intercepted XHR responses into
  promos with a single call.
- ``make_promo()``  now generates stable IDs (MD5 of bankId + title + href)
  instead of ``abs(hash(title)) % 100_000``, avoiding collisions and drift
  when titles change by one character.
- Module-level compiled regexes (no more ``import re`` inside a method).
"""
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

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

try:
    from playwright_stealth import stealth_sync
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False


# ── Module-level compiled patterns ────────────────────────────────
_RE_BOLD_STAR = re.compile(r'\*\*(.*?)\*\*')
_RE_BOLD_UNDER = re.compile(r'__(.*?)__')

# ── Stealth browser headers ────────────────────────────────────────
STEALTH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
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

    Subclasses must set class-level attributes and implement
    ``scrape_api()`` and ``scrape_html()``.  SPA scrapers also override
    ``scrape_playwright()`` and set ``requires_playwright = True``.

    Fallback order:  API → HTML → Playwright.
    """

    bank_id: str
    bank_name: str
    bank_url: str
    bank_color: str
    bank_short: str

    # Set to True in SPA scrapers; read by main.py to honour --skip-playwright
    # without a hard-coded list of bank IDs.
    requires_playwright: bool = False

    def __init__(self) -> None:
        self.reports_dir = Path("reports") / self.bank_id
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    # ── Public entry-point ──────────────────────────────────────────
    def scrape(self) -> list[dict]:
        methods_tried: list[str] = []

        for label, method in (("api", self.scrape_api), ("html", self.scrape_html)):
            try:
                promos = method()
                if promos:
                    self._save_report({"method": label, "count": len(promos), "success": True})
                    return promos
                methods_tried.append(label)          # returned empty, fall through
            except NotImplementedError:
                methods_tried.append(f"{label}:not_implemented")
            except Exception as exc:
                methods_tried.append(f"{label}:{type(exc).__name__}:{exc}")

        if HAS_PLAYWRIGHT:
            try:
                promos = self.scrape_playwright()
                self._save_report({
                    "method": "playwright",
                    "count": len(promos),
                    "success": bool(promos),
                })
                return promos
            except Exception as exc:
                methods_tried.append(f"playwright:{type(exc).__name__}:{exc}")

        self._save_report({
            "method": "all_failed",
            "methods_tried": methods_tried,
            "success": False,
        })
        return []

    # ── Abstract methods (must be implemented by subclasses) ────────
    @abstractmethod
    def scrape_api(self) -> list[dict]:
        """Fetch from an API endpoint.  Raise ``NotImplementedError`` if N/A."""

    @abstractmethod
    def scrape_html(self) -> list[dict]:
        """Fetch raw HTML via httpx and parse with BeautifulSoup."""

    # ── Generic Playwright fallback (override for custom SPA logic) ─
    def scrape_playwright(self, scroll: bool = False) -> list[dict]:
        """Headless Chromium via Playwright.  Override for SPA-specific logic."""
        with self.open_playwright_page() as (page, _):
            page.goto(self.bank_url, wait_until="domcontentloaded", timeout=45_000)
            if scroll:
                self._scroll_infinite(page)
            else:
                page.wait_for_timeout(5_000)
            html = page.content()
            self._save_html_sample(html, "playwright")
            return self._parse_common(BeautifulSoup(html, "html.parser"))

    # ── Playwright context manager ──────────────────────────────────
    @contextmanager
    def open_playwright_page(
        self,
        *,
        intercept_json: bool = False,
        url_keywords: list[str] | None = None,
    ):
        """Shared Playwright setup: Chromium + stealth + optional JSON interception.

        Eliminates the ~30-line boilerplate that was duplicated across all
        SPA scrapers (GNB, Continental, Itaú, PersonalPay).

        Parameters
        ----------
        intercept_json:
            Attach a ``response`` listener that appends JSON XHR/fetch calls
            to the ``intercepted`` list yielded alongside ``page``.
        url_keywords:
            When set, only capture responses whose URL contains at least one
            of the keywords (case-insensitive match).

        Yields
        ------
        (page, intercepted)
            ``page`` is a Playwright ``Page``; ``intercepted`` is a
            ``list[dict]`` with ``{"url": str, "data": any}`` entries.

        Usage
        -----
        ::

            with self.open_playwright_page(intercept_json=True,
                                           url_keywords=["api/beneficios"]) as (page, responses):
                page.goto(self.bank_url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(6_000)
                promos = self._promos_from_intercepted(responses)
        """
        if not HAS_PLAYWRIGHT:
            raise RuntimeError("playwright not installed")

        intercepted: list[dict] = []

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
            if intercept_json:
                page.on("response", self._make_json_interceptor(intercepted, url_keywords))
            try:
                yield page, intercepted
            finally:
                browser.close()

    def _make_json_interceptor(
        self,
        bucket: list[dict],
        url_keywords: list[str] | None = None,
    ):
        """Return a Playwright response handler that appends JSON calls to ``bucket``."""
        def handler(response) -> None:
            try:
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                if url_keywords and not any(kw in response.url.lower() for kw in url_keywords):
                    return
                bucket.append({"url": response.url, "data": response.json()})
            except Exception:
                pass
        return handler

    # ── HTTP helpers ────────────────────────────────────────────────
    def fetch_html(self, url: str | None = None, *, timeout: int = 20) -> str:
        """GET a URL with stealth headers; return response text."""
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
        """GET a JSON endpoint; return parsed data."""
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

    # ── JSON parsing helpers ────────────────────────────────────────
    def _extract_item_fields(
        self, item: dict
    ) -> tuple[str, str | None, str, str, str | None]:
        """Extract promo fields from a JSON dict, handling Spanish/English key variants.

        Centralises the ``item.get("nombre") or item.get("name") or ...``
        pattern that was duplicated in five ``scrape_api()`` methods.

        Returns
        -------
        (title, desc, img, href, category)
        """
        title = (
            item.get("nombre") or item.get("name") or
            item.get("titulo") or item.get("title") or ""
        )
        desc = item.get("descripcion") or item.get("description")
        img_raw = item.get("imagen") or item.get("image") or ""
        img = img_raw.get("url", "") if isinstance(img_raw, dict) else (img_raw or "")
        href = item.get("url") or item.get("link") or ""
        # Category may arrive as a nested object {id, name, order, active, image, headerImage}
        # (seen in Continental's and GNB's APIs).  Always coerce to a plain string.
        category_raw = item.get("categoria") or item.get("category")
        if isinstance(category_raw, dict):
            category: str | None = category_raw.get("nombre") or category_raw.get("name") or None
        else:
            category = str(category_raw) if category_raw else None
        return str(title), desc, str(img), str(href), category

    def _parse_api_items(
        self,
        items: list,
        *,
        title_cleaner=None,
    ) -> list[dict]:
        """Build promos from a list of JSON dicts via ``_extract_item_fields``.

        Skips items with no title, title ≤ 2 chars, or no payload at all
        (no desc, img, or href).

        Parameters
        ----------
        items:
            Raw dicts from an API response.
        title_cleaner:
            Optional ``callable(str) -> str`` applied to each title after
            extraction.  Return an empty string to discard the item.
        """
        promos: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title, desc, img, href, category = self._extract_item_fields(item)
            if not title or len(title) <= 2:
                continue
            if title_cleaner:
                title = title_cleaner(title)
                if not title:
                    continue
            # Require at least one payload field beyond the title
            if not desc and not img and not href:
                continue
            promos.append(self.make_promo(
                title=title,
                desc=desc.strip() if desc else None,
                img=img,
                href=href,
                category=category,
            ))
        return promos

    def _unwrap_api_response(self, data: dict | list) -> list:
        """Extract the items list from common API response envelopes.

        Handles bare lists and dicts with wrapper keys such as
        ``data``, ``items``, ``comercios``, ``beneficios``, ``results``.
        """
        if isinstance(data, list):
            return data
        for key in ("data", "items", "comercios", "beneficios", "results"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return []

    def _promos_from_intercepted(
        self,
        api_responses: list[dict],
        *,
        title_cleaner=None,
    ) -> list[dict]:
        """Build promos from all JSON responses captured by the Playwright interceptor."""
        promos: list[dict] = []
        for resp in api_responses:
            items = self._unwrap_api_response(resp["data"])
            promos.extend(self._parse_api_items(items, title_cleaner=title_cleaner))
        return promos

    # ── Promo factory ───────────────────────────────────────────────
    def make_promo(
        self,
        title: str,
        desc: str | None = None,
        img: str = "",
        href: str = "",
        category: str | None = None,
    ) -> dict:
        if href and not href.startswith("http"):
            href = urljoin(self.bank_url, href)

        if desc is not None:
            # Convert HTML to plain text, preserving explicit line-breaks
            soup = BeautifulSoup(desc, "html.parser")
            for br in soup.find_all("br"):
                br.replace_with("\n")
            desc = soup.get_text()
            # Strip markdown bold/italic markers
            desc = _RE_BOLD_STAR.sub(r'\1', desc)
            desc = _RE_BOLD_UNDER.sub(r'\1', desc)
            desc = desc.strip() or None

        # Stable ID: MD5 of (bankId | normalised title | href).
        # Anchoring on href makes the ID survive minor title edits.
        # Using MD5 hex[:8] gives ~4 billion buckets vs the old
        # abs(hash(title)) % 100_000 which had only 100 k.
        id_source = f"{self.bank_id}|{title.lower().strip()}|{href}".encode()
        stable_id = f"{self.bank_id}-{hashlib.md5(id_source).hexdigest()[:8]}"

        return {
            "id": stable_id,
            "title": title.strip(),
            "desc": desc,
            "img": img,
            "href": href,
            "bankId": self.bank_id,
            "bankShort": self.bank_short,
            "bankColor": self.bank_color,
            "category": category,
        }

    # ── Reports ─────────────────────────────────────────────────────
    def _save_report(self, data: dict) -> None:
        data["timestamp"] = datetime.now().isoformat()
        data["url"] = self.bank_url
        data["bank_id"] = self.bank_id
        (self.reports_dir / f"report_{int(time.time())}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2)
        )

    def _save_html_sample(self, html: str, method: str) -> None:
        (self.reports_dir / f"html_{method}_{int(time.time())}.html").write_text(html[:5000])

    # ── Playwright helpers ──────────────────────────────────────────
    def _scroll_infinite(self, page, rounds: int = 5, delay: int = 2_000) -> None:
        """Scroll to bottom repeatedly for infinite-scroll pages."""
        for _ in range(rounds):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(delay)
            try:
                page.wait_for_load_state("networkidle", timeout=5_000)
            except Exception:
                pass

    # ── Generic DOM parser ──────────────────────────────────────────
    def _parse_common(self, soup: BeautifulSoup) -> list[dict]:
        """Try common CSS selectors to find promo cards (generic fallback)."""
        selectors = [
            ".promo-card", ".promocion", '[class*="benefit"]', '[class*="card"]',
            "article", ".item", ".promo", '[class*="promo"]', ".entry",
        ]
        promos: list[dict] = []
        for sel in selectors:
            for el in soup.select(sel)[:40]:
                title_el = el.select_one("h1,h2,h3,h4,h5,.title,.name")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title or not (3 < len(title) < 200):
                    continue
                img_tag = el.select_one("img")
                img_url = ""
                if img_tag and img_tag.get("src"):
                    src = img_tag["src"]
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
