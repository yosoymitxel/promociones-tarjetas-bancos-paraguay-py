"""
Individual bank scrapers for Paraguayan bank promotions.

Structure
---------
Each scraper implements ``scrape_api()`` and ``scrape_html()``.
SPA scrapers that cannot function without a real browser override
``scrape_playwright()`` and declare ``requires_playwright = True``.

All Playwright boilerplate (browser launch, stealth, JSON interception)
now lives in ``ScraperBase.open_playwright_page()``; each SPA scraper
is ~20 lines instead of ~80.
"""
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper_modules.base import ScraperBase, HAS_PLAYWRIGHT


# ══════════════════════════════════════════════════════════════════
#  BASA  ·  https://www.bancobasa.com.py/promociones-personas
#
#  Two-phase scrape:
#    Phase 1 — httpx (fast, no Playwright needed):
#              scrapes the page HTML for the full list of promos.
#    Phase 2 — Playwright (optional enrichment):
#              downloads each alianza PDF, parses it for structured
#              fields (validity, discount, days, installments) and
#              writes the result to desc.  Unchanged PDFs are served
#              from a content-hash cache — no re-download, no re-parse.
#
#  requires_playwright stays False because Phase 1 alone is useful.
#  Phase 2 activates automatically when Playwright is available.
# ══════════════════════════════════════════════════════════════════
class BASAScraper(ScraperBase):
    bank_id    = "basa"
    bank_name  = "Banco BASA"
    bank_url   = "https://www.bancobasa.com.py/promociones-personas"
    bank_color = "#F59E0B"
    bank_short = "BASA"

    # Playwright is NOT required — Phase 1 works without it.
    # Phase 2 (PDF enrichment) will simply be skipped if it is absent.
    requires_playwright = False

    def scrape_api(self) -> list[dict]:
        raise NotImplementedError("BASA has no public API")

    def scrape_html(self) -> list[dict]:
        html = self.fetch_html()
        self._save_html_sample(html, "html")
        return self._parse_basa(BeautifulSoup(html, "html.parser"))

    # ── Override scrape() to add Phase 2 after the base HTML scrape ─
    def scrape(self) -> list[dict]:
        """Phase 1 (HTML) + optional Phase 2 (PDF enrichment)."""
        promos = super().scrape()           # runs scrape_api → scrape_html

        if promos and HAS_PLAYWRIGHT:
            promos = self._enrich_with_pdfs(promos)

        return promos

    # ── Phase 2 — PDF enrichment ─────────────────────────────────────
    def _enrich_with_pdfs(self, promos: list[dict]) -> list[dict]:
        """
        Download and parse alianza PDFs using Playwright's authenticated
        session, then update each promo's ``desc`` field.

        Uses a content-hash cache so unchanged PDFs are never re-processed.
        Promos without a PDF href (e.g. highlighted cards) are left as-is.
        """
        # Lazy import — pdfplumber is optional; missing it disables enrichment
        try:
            from scraper_modules.basa_pdf import BASAPDFParser, PDFCache
        except ImportError:
            print("    [BASA] pdfplumber not installed — skipping PDF enrichment")
            return promos

        pdf_promos = [p for p in promos if "/pdf/" in p.get("href", "")]
        if not pdf_promos:
            return promos

        parser = BASAPDFParser()
        cache  = PDFCache()

        print(f"    [BASA] {len(pdf_promos)} PDF(s) to check "
              f"(cache has {cache.stats()['total_entries']} entries)…")

        counts = {"cached": 0, "parsed": 0, "error": 0}

        # Build a lookup from href → promo so we can update in-place
        pdf_map: dict[str, dict] = {p["href"]: p for p in pdf_promos}

        with self.open_playwright_page() as (page, _):
            # Visit main page first to establish the browser session / cookies
            # that unlock the PDF storage URLs (direct httpx calls get 403).
            page.goto(self.bank_url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(2_000)

            for href, promo in pdf_map.items():
                title   = promo["title"]
                pdf_url = href if href.startswith("http") else urljoin(self.bank_url, href)

                try:
                    # page.request inherits the browser's cookies + headers
                    resp      = page.request.get(pdf_url, timeout=20_000)
                    pdf_bytes = resp.body()

                    if not pdf_bytes or len(pdf_bytes) < 512:
                        raise ValueError(f"empty response ({len(pdf_bytes)} bytes)")

                    if cache.needs_parse(pdf_url, pdf_bytes):
                        parsed = parser.parse(pdf_bytes, commerce_name=title)
                        cache.store(pdf_url, pdf_bytes, parsed)
                        counts["parsed"] += 1
                        status = "PARSED"
                    else:
                        parsed = cache.get(pdf_url)
                        counts["cached"] += 1
                        status = "CACHED"

                    # Enrich promo in-place
                    if parsed:
                        if parsed.get("desc"):
                            promo["desc"] = parsed["desc"]
                        if parsed.get("validity") and not promo.get("validity"):
                            promo["validity"] = parsed["validity"]
                        if parsed.get("discount_percent") and not promo.get("discount_percent"):
                            promo["discount_percent"] = parsed["discount_percent"]
                        if parsed.get("days") and not promo.get("days"):
                            promo["days"] = parsed["days"]
                        if parsed.get("installments") is not None and "installments" not in promo:
                            promo["installments"] = parsed["installments"]

                    print(f"      [{status}] {title[:50]}")

                except Exception as exc:
                    counts["error"] += 1
                    print(f"      [ERROR]  {title[:50]}: {exc}")

        cache.save()   # no-op if nothing changed

        print(f"    [BASA] PDF enrichment done — "
              f"{counts['parsed']} parsed, {counts['cached']} cached, "
              f"{counts['error']} errors")

        return promos

    # ── HTML parser (shared by both phases) ──────────────────────────
    def _parse_basa(self, soup: BeautifulSoup) -> list[dict]:
        promos: list[dict] = []
        seen: set[str] = set()

        def _add(title: str, img_url: str, href: str) -> None:
            key = title.lower().strip()
            if key in seen or not (2 < len(title) < 200):
                return
            if "conoce más acá" in key:
                return
            seen.add(key)
            promos.append(self.make_promo(title=title, img=img_url, href=href))

        # Pass 1: cards with dedicated images (sección "Destacadas")
        for item in soup.select(".row .col-md-4, .row .col-md-3, .row .col-6"):
            h5 = item.select_one("h5")
            if not h5:
                continue
            title = h5.get_text(strip=True)
            img_tag = item.select_one("img")
            img_url = ""
            if img_tag:
                src = img_tag.get("src", "") or img_tag.get("data-src", "")
                if src:
                    img_url = src if src.startswith("http") else urljoin(self.bank_url, src)
            link = item.select_one("a[href]")
            href = link.get("href", "") if link else ""
            if img_url or href:
                _add(title, img_url, href)

        # Pass 2: PDF links (sección "Alianzas")
        # No image here — see the comment in the previous version for why.
        for a_tag in soup.select('a[href*="/storage/app/media/pdf/bases-condiciones/"]'):
            title = a_tag.get_text(strip=True)
            href  = a_tag.get("href", "")
            _add(title, img_url="", href=href)

        return promos


# ══════════════════════════════════════════════════════════════════
#  eCLUB  ·  https://eclub.com.py/promociones/
#  WordPress / Elementor — promos visible in static HTML
# ══════════════════════════════════════════════════════════════════
class EClubScraper(ScraperBase):
    bank_id    = "eclub"
    bank_name  = "eClub"
    bank_url   = "https://eclub.com.py/promociones/"
    bank_color = "#EC4899"
    bank_short = "eClub"

    _SKIP_TITLES = frozenset({
        "descargá eclub",
        "encontranos en las redes",
        "escribinos con confianza",
        "¿qué sorteamos?",
    })

    def scrape_api(self) -> list[dict]:
        raise NotImplementedError("eClub has no public API")

    def scrape_html(self) -> list[dict]:
        html = self.fetch_html()
        self._save_html_sample(html, "html")
        return self._parse_eclub(BeautifulSoup(html, "html.parser"))

    def _parse_eclub(self, soup: BeautifulSoup) -> list[dict]:
        # Each promo lives in an Elementor section: <h2> + <p> + optional <a>.
        # Deduplication is handled centrally by main.py — no need to do it here.
        promos: list[dict] = []
        for section in soup.select(".elementor-section, .elementor-widget-wrap, .e-con"):
            h2 = section.select_one("h2")
            if not h2:
                continue
            title = h2.get_text(strip=True)
            if not title or not (5 <= len(title) <= 200):
                continue
            if title.lower() in self._SKIP_TITLES:
                continue
            if "sorteo" in title.lower() or "descubrí" in title.lower():
                continue

            desc_el = section.select_one("p")
            desc = desc_el.get_text(strip=True) if desc_el else None

            img_tag = section.select_one("img[data-src], img[src]")
            img_url = ""
            if img_tag:
                src = img_tag.get("data-src", "") or img_tag.get("src", "")
                if src and not src.startswith("data:"):
                    img_url = src if src.startswith("http") else urljoin(self.bank_url, src)

            link = section.select_one('a[href*=".pdf"]')
            href = link.get("href", "") if link else ""

            if desc or img_url or href:
                promos.append(self.make_promo(
                    title=title,
                    desc=desc,
                    img=img_url,
                    href=href,
                ))
        return promos


# ══════════════════════════════════════════════════════════════════
#  GNB  ·  https://www.beneficiosbancognb.com.py/v2/beneficios/categorias
#  Angular SPA — requires Playwright (or direct API interception)
# ══════════════════════════════════════════════════════════════════
class GNBScraper(ScraperBase):
    bank_id            = "gnb"
    bank_name          = "Banco GNB"
    bank_url           = "https://www.beneficiosbancognb.com.py/v2/beneficios/categorias"
    bank_color         = "#10B981"
    bank_short         = "GNB"
    requires_playwright = True

    _api_candidates = [
        "https://www.beneficiosbancognb.com.py/v2/api/categorias",
        "https://www.beneficiosbancognb.com.py/v2/api/beneficios",
        "https://www.beneficiosbancognb.com.py/api/categorias",
        "https://www.beneficiosbancognb.com.py/api/beneficios",
    ]

    @staticmethod
    def _clean_title(title: str) -> str:
        """Strip redundant "GNB" / "Día GNB" prefixes from titles."""
        return " ".join(title.replace("Día GNB", "").replace("GNB", "").split())

    def scrape_api(self) -> list[dict]:
        for url in self._api_candidates:
            try:
                data  = self.fetch_json(url, timeout=10)
                items = self._unwrap_api_response(data)
                promos = self._parse_api_items(items, title_cleaner=self._clean_title)
                if promos:
                    return promos
            except Exception:
                continue
        raise NotImplementedError("No GNB API endpoints responded")

    def scrape_html(self) -> list[dict]:
        raise NotImplementedError("GNB is an Angular SPA — static HTML has no data")

    def scrape_playwright(self) -> list[dict]:
        url_kws = ["beneficio", "categori", "comerci", "promo"]
        with self.open_playwright_page(intercept_json=True, url_keywords=url_kws) as (page, responses):
            page.goto(self.bank_url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(6_000)

            # Click category links to trigger extra API calls
            try:
                for link in page.query_selector_all(
                    'a[href*="beneficio"], [class*="categoria"], [class*="category"]'
                )[:3]:
                    try:
                        link.click()
                        page.wait_for_timeout(2_000)
                    except Exception:
                        pass
            except Exception:
                pass

            promos = self._promos_from_intercepted(responses, title_cleaner=self._clean_title)

            if not promos:
                html = page.content()
                self._save_html_sample(html, "playwright")
                promos = self._parse_common(BeautifulSoup(html, "html.parser"))

        return promos


# ══════════════════════════════════════════════════════════════════
#  ITAÚ  ·  https://www.itau.com.py/beneficios
#  SPA — requires Playwright; crawls category pages for DOM data
# ══════════════════════════════════════════════════════════════════
class ItaúScraper(ScraperBase):
    bank_id            = "itau"
    bank_name          = "Itaú Paraguay"
    bank_url           = "https://www.itau.com.py/beneficios"
    bank_color         = "#FF6B00"
    bank_short         = "Itaú"
    requires_playwright = True

    _api_candidates = [
        "https://www.itau.com.py/api/beneficios",
        "https://www.itau.com.py/api/v1/beneficios",
        "https://www.itau.com.py/beneficios/api",
    ]

    # Fallback categories if the main page carousel returns nothing
    _fallback_categories: dict[str, str] = {
        "https://www.itau.com.py/beneficios2/categoria/7":  "Gastronomía",
        "https://www.itau.com.py/beneficios2/categoria/13": "Supermercados",
        "https://www.itau.com.py/beneficios2/categoria/3":  "Belleza y Salud",
        "https://www.itau.com.py/beneficios2/categoria/39": "Niños",
        "https://www.itau.com.py/beneficios2/categoria/10": "Educación",
        "https://www.itau.com.py/beneficios2/categoria/11": "Itaú Personal Bank",
        "https://www.itau.com.py/beneficios2/categoria/15": "Recreación",
        "https://www.itau.com.py/beneficios2/categoria/20": "Restaurantes",
    }

    def scrape_api(self) -> list[dict]:
        for url in self._api_candidates:
            try:
                data  = self.fetch_json(url, timeout=10)
                items = self._unwrap_api_response(data)
                promos = self._parse_api_items(items)
                if promos:
                    return promos
            except Exception:
                continue
        raise NotImplementedError("No Itaú API found")

    def scrape_html(self) -> list[dict]:
        raise NotImplementedError("Itaú is a SPA")

    def scrape_playwright(self) -> list[dict]:
        # Itaú renders data entirely in the DOM (no useful XHR to intercept),
        # so we navigate to each category page and scrape a.item-oferta cards.
        promos: list[dict] = []

        with self.open_playwright_page() as (page, _):
            # 1. Discover category URLs from the main page carousel
            print("    [Itaú] Loading main page to gather categories…")
            page.goto(self.bank_url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(5_000)

            category_map: dict[str, str | None] = {}
            for el in page.query_selector_all('a[href*="/beneficios2/categoria/"]'):
                href = el.get_attribute("href")
                if not href:
                    continue
                url = urljoin(self.bank_url, href)
                if url not in category_map:
                    name_el = el.query_selector("span.una-linea")
                    category_map[url] = name_el.inner_text().strip() if name_el else None

            if not category_map:
                print("    [Itaú] No categories on main page — using fallback list.")
                category_map = dict(self._fallback_categories)

            print(f"    [Itaú] Crawling {len(category_map)} categories…")

            # 2. Crawl each category page (cap at 12 to stay within time budget)
            for cat_url, category_name in list(category_map.items())[:12]:
                try:
                    page.goto(cat_url, wait_until="domcontentloaded", timeout=30_000)
                    page.wait_for_timeout(4_050)

                    cards = page.query_selector_all("a.item-oferta")
                    if not cards:
                        continue

                    print(f"    [Itaú] {len(cards)} items — {category_name or cat_url}")

                    for card in cards:
                        try:
                            title_el = card.query_selector("h6")
                            title = title_el.inner_text().strip() if title_el else ""
                            if not title:
                                continue

                            discount_el = card.query_selector("small:nth-of-type(1)")
                            discount    = discount_el.inner_text().strip() if discount_el else ""

                            payment_el = card.query_selector("small:nth-of-type(2)")
                            payment    = payment_el.inner_text().strip() if payment_el else ""

                            desc = (
                                f"{discount} con {payment}"
                                if discount and payment
                                else (discount or payment)
                            )

                            img_el  = card.query_selector("span img")
                            img_url = ""
                            if img_el:
                                src = img_el.get_attribute("src")
                                if src:
                                    img_url = urljoin(cat_url, src)

                            href      = card.get_attribute("href")
                            promo_url = urljoin(cat_url, href) if href else cat_url

                            promos.append(self.make_promo(
                                title=title,
                                desc=desc or None,
                                img=img_url,
                                href=promo_url,
                                category=category_name,
                            ))
                        except Exception:
                            continue

                except Exception as exc:
                    print(f"    [Itaú] {cat_url} error: {exc}")
                    continue

        return promos


# ══════════════════════════════════════════════════════════════════
#  CONTINENTAL  ·  https://www.bancontinental.com.py/#/club-continental/comercios
#  Angular SPA — requires Playwright
# ══════════════════════════════════════════════════════════════════
class ContinentalScraper(ScraperBase):
    bank_id            = "continental"
    bank_name          = "Banco Continental"
    bank_url           = "https://www.bancontinental.com.py/#/club-continental/comercios"
    bank_color         = "#3B82F6"
    bank_short         = "Continental"
    requires_playwright = True

    _api_candidates = [
        "https://www.bancontinental.com.py/api/club-continental/comercios",
        "https://www.bancontinental.com.py/api/v1/comercios",
        "https://www.bancontinental.com.py/api/beneficios",
    ]

    def scrape_api(self) -> list[dict]:
        for url in self._api_candidates:
            try:
                data  = self.fetch_json(url, timeout=10)
                items = self._unwrap_api_response(data)
                promos = self._parse_api_items(items)
                if promos:
                    return promos
            except Exception:
                continue
        raise NotImplementedError("No Continental API found")

    def scrape_html(self) -> list[dict]:
        raise NotImplementedError("Continental is an Angular SPA")

    def scrape_playwright(self) -> list[dict]:
        with self.open_playwright_page(intercept_json=True) as (page, responses):
            page.goto(self.bank_url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(8_000)

            promos = self._promos_from_intercepted(responses)

            if not promos:
                html = page.content()
                self._save_html_sample(html, "playwright")
                promos = self._parse_common(BeautifulSoup(html, "html.parser"))

        return promos


# ══════════════════════════════════════════════════════════════════
#  PERSONAL PAY  ·  https://www.personalpay.com.py/beneficios
#  SPA + Cloudflare protection — requires Playwright
# ══════════════════════════════════════════════════════════════════
class PersonalPayScraper(ScraperBase):
    bank_id            = "personalpay"
    bank_name          = "Personal Pay"
    bank_url           = "https://www.personalpay.com.py/beneficios"
    bank_color         = "#8B5CF6"
    bank_short         = "PersonalPay"
    requires_playwright = True

    _api_candidates = [
        "https://www.personalpay.com.py/api/beneficios",
        "https://www.personalpay.com.py/api/v1/beneficios",
    ]

    def scrape_api(self) -> list[dict]:
        for url in self._api_candidates:
            try:
                data  = self.fetch_json(url, timeout=10)
                items = self._unwrap_api_response(data)
                promos = self._parse_api_items(items)
                if promos:
                    return promos
            except Exception:
                continue
        raise NotImplementedError("No PersonalPay API found")

    def scrape_html(self) -> list[dict]:
        html = self.fetch_html()
        self._save_html_sample(html, "html")
        if "cloudflare" in html.lower() or "challenge" in html.lower():
            raise RuntimeError("Cloudflare protection detected")
        return self._parse_common(BeautifulSoup(html, "html.parser"))

    def scrape_playwright(self) -> list[dict]:
        url_kws = ["beneficio", "promo", "descuento"]
        with self.open_playwright_page(intercept_json=True, url_keywords=url_kws) as (page, responses):
            page.goto(self.bank_url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(10_000)   # Extra time for Cloudflare JS challenge

            promos = self._promos_from_intercepted(responses)

            if not promos:
                html = page.content()
                self._save_html_sample(html, "playwright")
                if "challenge" in html.lower() and len(html) < 5_000:
                    raise RuntimeError("Cloudflare challenge not bypassed")
                promos = self._parse_common(BeautifulSoup(html, "html.parser"))

        return promos
