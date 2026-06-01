"""
Individual bank scrapers for Paraguayan bank promotions.

Each scraper implements scrape_api() and scrape_html(), with a Playwright
fallback inherited from ScraperBase (or overridden for SPAs).
"""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper_modules.base import ScraperBase, HAS_PLAYWRIGHT

if HAS_PLAYWRIGHT:
    from playwright.sync_api import sync_playwright
    try:
        from playwright_stealth import stealth_sync
    except ImportError:
        stealth_sync = None  # type: ignore


# ═══════════════════════════════════════════════════════════════════
#  BASA  — https://www.bancobasa.com.py/promociones-personas
#  Static HTML (OctoberCMS) — 180+ alianzas parseable via HTTP
# ═══════════════════════════════════════════════════════════════════
class BASAScraper(ScraperBase):
    bank_id = "basa"
    bank_name = "Banco BASA"
    bank_url = "https://www.bancobasa.com.py/promociones-personas"
    bank_color = "#F59E0B"
    bank_short = "BASA"

    def scrape_api(self) -> list[dict]:
        raise NotImplementedError("BASA has no public API")

    def scrape_html(self) -> list[dict]:
        html = self.fetch_html()
        self._save_html_sample(html, "html")
        soup = BeautifulSoup(html, "html.parser")
        promos: list[dict] = []

        # BASA page structure:
        # - "destacadas" section: cards with <img> + <h5> inside .col divs
        # - "alianzas" section: list items with <a> + <h5>
        # We look for all <h5> tags inside promotion containers

        # Method 1: Look for promo items with images (destacadas section)
        for item in soup.select(".row .col-md-4, .row .col-md-3, .row .col-6"):
            h5 = item.select_one("h5")
            if not h5:
                continue
            title = h5.get_text(strip=True)
            if not title or len(title) < 2 or len(title) > 200:
                continue
            # Skip titles containing "conoce más acá"
            if "conoce más acá" in title.lower():
                continue


            # Get image
            img_tag = item.select_one("img")
            img_url = ""
            if img_tag:
                src = img_tag.get("src", "") or img_tag.get("data-src", "")
                if src:
                    img_url = src if src.startswith("http") else urljoin(self.bank_url, src)

            # Get link to PDF (bases y condiciones)
            link = item.select_one("a[href]")
            href = ""
            if link:
                href = link.get("href", "")

            # Only add if we have at least an image or a link
            if img_url or href:
                promos.append(self.make_promo(
                    title=title,
                    desc=None,
                    img=img_url,
                    href=href,
                ))

        # Method 2: If method 1 didn't find much, try broader search
        if len(promos) < 5:
            # Find all links pointing to PDF files (bases y condiciones)
            for a_tag in soup.select('a[href*="/storage/app/media/pdf/bases-condiciones/"]'):
                title = a_tag.get_text(strip=True)
                if not title or len(title) < 2 or len(title) > 200:
                    continue
                # Skip titles containing "conoce más acá"
                if "conoce más acá" in title.lower():
                    continue

                # Skip duplicates
                if any(p["title"].lower() == title.lower() for p in promos):
                    continue

                href = a_tag.get("href", "")

                # Try to find associated image
                parent = a_tag.parent
                img_tag = parent.select_one("img") if parent else None
                img_url = ""
                if img_tag:
                    src = img_tag.get("src", "") or img_tag.get("data-src", "")
                    if src:
                        img_url = src if src.startswith("http") else urljoin(self.bank_url, src)

                # Only add if we have at least an image or a link (href should be non-empty from the selector, but we check anyway)
                if img_url or href:
                    promos.append(self.make_promo(
                        title=title,
                        img=img_url,
                        href=href,
                    ))

        return promos


# ═══════════════════════════════════════════════════════════════════
#  eCLUB  — https://eclub.com.py/promociones/
#  WordPress/Elementor — promotions visible in static HTML
# ═══════════════════════════════════════════════════════════════════
class EClubScraper(ScraperBase):
    bank_id = "eclub"
    bank_name = "eClub"
    bank_url = "https://eclub.com.py/promociones/"
    bank_color = "#EC4899"
    bank_short = "eClub"

    def scrape_api(self) -> list[dict]:
        raise NotImplementedError("eClub has no public API")

    def scrape_html(self) -> list[dict]:
        html = self.fetch_html()
        self._save_html_sample(html, "html")
        soup = BeautifulSoup(html, "html.parser")
        promos: list[dict] = []

        # eClub uses Elementor sections, each promo is in a section with h2 + paragraph
        # Structure: <section> → <h2>Promo Title</h2> → <p>description</p> → <a>Bases y Condiciones</a>

        # Try Elementor widget containers
        for section in soup.select(".elementor-section, .elementor-widget-wrap, .e-con"):
            h2 = section.select_one("h2")
            if not h2:
                continue
            title = h2.get_text(strip=True)
            if not title or len(title) < 5 or len(title) > 200:
                continue
            # Skip navigation/generic headings
            if title.lower() in ("descargá eclub", "encontranos en las redes", "escribinos con confianza", "¿qué sorteamos?"):
                continue
            # Skip titles containing "sorteo" or "descubrí"
            if "sorteo" in title.lower() or "descubrí" in title.lower():
                continue

            # Get description from first paragraph
            desc_el = section.select_one("p")
            desc = desc_el.get_text(strip=True) if desc_el else None

            # Get image
            img_tag = section.select_one("img[data-src], img[src]")
            img_url = ""
            if img_tag:
                src = img_tag.get("data-src", "") or img_tag.get("src", "")
                if src and not src.startswith("data:"):
                    img_url = src if src.startswith("http") else urljoin(self.bank_url, src)

            # Link to bases y condiciones
            link = section.select_one('a[href*=".pdf"]')
            href = ""
            if link:
                href = link.get("href", "")

            # Only add if we have at least one of: description, image, or link
            if desc or img_url or href:
                promos.append(self.make_promo(
                    title=title,
                    desc=desc,
                    img=img_url,
                    href=href,
                ))

        # Deduplicate by title
        seen = set()
        unique = []
        for p in promos:
            key = p["title"].lower().strip()
            if key not in seen:
                seen.add(key)
                unique.append(p)

        return unique


# ═══════════════════════════════════════════════════════════════════
#  GNB  — https://www.beneficiosbancognb.com.py/v2/beneficios/categorias
#  Angular SPA — requires Playwright to render, or API interception
# ═══════════════════════════════════════════════════════════════════
class GNBScraper(ScraperBase):
    bank_id = "gnb"
    bank_name = "Banco GNB"
    bank_url = "https://www.beneficiosbancognb.com.py/v2/beneficios/categorias"
    bank_color = "#10B981"
    bank_short = "GNB"

    # Known API endpoints to try (Angular apps often have REST backends)
    _api_candidates = [
        "https://www.beneficiosbancognb.com.py/v2/api/categorias",
        "https://www.beneficiosbancognb.com.py/v2/api/beneficios",
        "https://www.beneficiosbancognb.com.py/api/categorias",
        "https://www.beneficiosbancognb.com.py/api/beneficios",
    ]

    def scrape_api(self) -> list[dict]:
        """Try known API endpoints that the Angular SPA might call."""
        for url in self._api_candidates:
            try:
                data = self.fetch_json(url, timeout=10)
                if isinstance(data, list) and len(data) > 0:
                    promos = []
                    for item in data:
                        title = item.get("nombre") or item.get("name") or item.get("titulo") or ""
                        if title:
                            # Clean title: remove "GNB" and "Día GNB"
                            title = title.replace("Día GNB", "").replace("GNB", "").strip()
                            title = ' '.join(title.split())
                            if not title:
                                continue
                            desc = item.get("descripcion") or item.get("description")
                            # Handle img field: might be a dict or string
                            img_raw = item.get("imagen") or item.get("image", "")
                            if isinstance(img_raw, dict):
                                img = img_raw.get("url", "")
                            else:
                                img = img_raw if isinstance(img_raw, str) else ""
                            href = item.get("url") or item.get("link", "")
                            # Only keep if we have a non-empty description or href (to filter out category-only entries)
                            if (desc is not None and desc.strip() != '') or (href is not None and href.strip() != ''):
                                promos.append(self.make_promo(
                                    title=title,
                                    desc=desc.strip() if desc else None,
                                    img=img,
                                    href=href,
                                ))
                    if promos:
                        return promos
            except Exception:
                continue
        raise NotImplementedError("No API endpoints responded")

    def scrape_html(self) -> list[dict]:
        raise NotImplementedError("GNB is a SPA — HTML is just a shell")

    def scrape_playwright(self, scroll: bool = False) -> list[dict]:
        """Use Playwright to render the Angular SPA and intercept API calls."""
        if not HAS_PLAYWRIGHT:
            raise RuntimeError("Playwright not installed")

        promos: list[dict] = []
        api_responses: list[dict] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                locale="es-PY",
                viewport={"width": 1440, "height": 900},
            )
            page = ctx.new_page()
            if stealth_sync:
                stealth_sync(page)

            # Intercept XHR/fetch responses for API data
            def handle_response(response):
                try:
                    url = response.url
                    if any(kw in url.lower() for kw in ["beneficio", "categori", "comerci", "promo"]):
                        if "application/json" in (response.headers.get("content-type", "")):
                            data = response.json()
                            api_responses.append({"url": url, "data": data})
                except Exception:
                    pass

            page.on("response", handle_response)

            try:
                page.goto(self.bank_url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(6_000)

                # Try to click on categories to trigger more API calls
                try:
                    category_links = page.query_selector_all('a[href*="beneficio"], [class*="categoria"], [class*="category"]')
                    for link in category_links[:3]:
                        try:
                            link.click()
                            page.wait_for_timeout(2_000)
                        except Exception:
                            pass
                except Exception:
                    pass

                # Parse intercepted API data
                for resp_data in api_responses:
                    data = resp_data["data"]
                    items = data if isinstance(data, list) else data.get("data", data.get("items", []))
                    if isinstance(items, list):
                        for item in items:
                         if isinstance(item, dict):
                             title = (
                                 item.get("nombre") or item.get("name") or
                                 item.get("titulo") or item.get("title") or ""
                             )
                             # Clean title: remove "GNB" and "Día GNB"
                             title = title.replace("Día GNB", "").replace("GNB", "").strip()
                             title = ' '.join(title.split())
                             if title and len(title) > 2:
                                    desc = item.get("descripcion") or item.get("description")
                                    # Handle img field: might be a dict or string
                                    img_raw = item.get("imagen") or item.get("image", "")
                                    if isinstance(img_raw, dict):
                                        img = img_raw.get("url", "")
                                    else:
                                        img = img_raw if isinstance(img_raw, str) else ""
                                    href = item.get("url") or item.get("link") or ""
                                    # Only keep if we have a non-empty description or href (to filter out category-only entries)
                                    if (desc is not None and desc.strip() != '') or (href is not None and href.strip() != ''):
                                        promos.append(self.make_promo(
                                            title=title,
                                            desc=desc.strip() if desc else None,
                                            img=img,
                                            href=href,
                                        ))

                # If API interception didn't work, parse the rendered DOM
                if not promos:
                    html = page.content()
                    self._save_html_sample(html, "playwright")
                    soup = BeautifulSoup(html, "html.parser")
                    promos = self._parse_common(soup)

            finally:
                browser.close()

        return promos


# ═══════════════════════════════════════════════════════════════════
#  ITAÚ  — https://www.itau.com.py/beneficios
#  SPA — requires Playwright
# ═══════════════════════════════════════════════════════════════════
class ItaúScraper(ScraperBase):
    bank_id = "itau"
    bank_name = "Itaú Paraguay"
    bank_url = "https://www.itau.com.py/beneficios"
    bank_color = "#FF6B00"
    bank_short = "Itaú"

    def scrape_api(self) -> list[dict]:
        # Try common API patterns
        api_candidates = [
            "https://www.itau.com.py/api/beneficios",
            "https://www.itau.com.py/api/v1/beneficios",
            "https://www.itau.com.py/beneficios/api",
        ]
        for url in api_candidates:
            try:
                data = self.fetch_json(url, timeout=10)
                if isinstance(data, list) and data:
                    promos = []
                    for item in data:
                        title = item.get("titulo") or item.get("title", "")
                        if title:
                            desc = item.get("descripcion") or item.get("description")
                            img = item.get("imagen") or item.get("image", "")
                            href = item.get("url") or item.get("link", "")
                            # Extract category if available
                            category = item.get("categoria") or item.get("category")
                            # Solo considerar como promoción si tiene al menos título y alguno de: descripción, imagen o enlace
                            if desc or img or href:
                                promos.append(self.make_promo(
                                    title=title,
                                    desc=desc,
                                    img=img,
                                    href=href,
                                    category=category,
                                ))
                    if promos:
                        return promos
            except Exception:
                continue
        raise NotImplementedError("No Itaú API found")

    def scrape_html(self) -> list[dict]:
        raise NotImplementedError("Itaú is a SPA")

    def scrape_playwright(self, scroll: bool = False) -> list[dict]:
        if not HAS_PLAYWRIGHT:
            raise RuntimeError("Playwright not installed")

        promos: list[dict] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                locale="es-PY",
                viewport={"width": 1440, "height": 900},
            )
            page = ctx.new_page()
            if stealth_sync:
                stealth_sync(page)

            try:
                # 1. Load main page to discover category URLs
                print("    [Itaú] Loading main page to gather categories...")
                page.goto(self.bank_url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(5_000)

                # Find all category links matching `/beneficios2/categoria/` and extract names from carousel
                elements = page.query_selector_all('a[href*="/beneficios2/categoria/"]')
                category_urls = []
                category_map = {}  # Map URL to category name
                for el in elements:
                    href = el.get_attribute("href")
                    if href:
                        url = urljoin(self.bank_url, href)
                        if url not in category_urls:
                            category_urls.append(url)
                            # Extract category name from span.una-linea
                            cat_name_el = el.query_selector("span.una-linea")
                            cat_name = cat_name_el.inner_text().strip() if cat_name_el else None
                            category_map[url] = cat_name

                # Fallback list of category URLs with names if main page returned none
                if not category_urls:
                    print("    [Itaú] No categories found on main page. Using fallback categories.")
                    category_urls = [
                        f"https://www.itau.com.py/beneficios2/categoria/{i}"
                        for i in [7, 13, 3, 39, 10, 11, 15, 20]
                    ]
                    category_map = {
                        "https://www.itau.com.py/beneficios2/categoria/7": "Gastronomía",
                        "https://www.itau.com.py/beneficios2/categoria/13": "Supermercados",
                        "https://www.itau.com.py/beneficios2/categoria/3": "Belleza y Salud",
                        "https://www.itau.com.py/beneficios2/categoria/39": "Niños",
                        "https://www.itau.com.py/beneficios2/categoria/10": "Educación",
                        "https://www.itau.com.py/beneficios2/categoria/11": "Itaú Personal Bank",
                        "https://www.itau.com.py/beneficios2/categoria/15": "Recreación",
                        "https://www.itau.com.py/beneficios2/categoria/20": "Restaurantes",
                    }

                print(f"    [Itaú] Crawling up to {len(category_urls)} categories for promotion grids...")
                
                # 2. Crawl each category page
                for cat_url in category_urls[:12]:  # Limit to run in reasonable time
                    try:
                        page.goto(cat_url, wait_until="domcontentloaded", timeout=30_000)
                        page.wait_for_timeout(4_050)
                        
                        # Use category name from main page carousel (pre-extracted)
                        category_name = category_map.get(cat_url)
                        
                        # Find all cards `a.item-oferta`
                        cards = page.query_selector_all("a.item-oferta")
                        if not cards:
                            continue

                        print(f"    [Itaú] Found {len(cards)} items in category: {category_name or cat_url}")

                        for card in cards:
                            try:
                                title_el = card.query_selector("h6")
                                title = title_el.inner_text().strip() if title_el else ""
                                if not title:
                                    continue

                                # Extract discount %
                                discount_el = card.query_selector("small:nth-of-type(1)")
                                discount_text = discount_el.inner_text().strip() if discount_el else ""

                                # Extract details (payment type)
                                payment_el = card.query_selector("small:nth-of-type(2)")
                                payment_text = payment_el.inner_text().strip() if payment_el else ""

                                # Combined description
                                desc = f"{discount_text} con {payment_text}" if discount_text and payment_text else (discount_text or payment_text)

                                # Extract image URL
                                img_el = card.query_selector("span img")
                                img_url = ""
                                if img_el:
                                    src = img_el.get_attribute("src")
                                    if src:
                                        img_url = urljoin(cat_url, src)

                                href = card.get_attribute("href")
                                promo_url = urljoin(cat_url, href) if href else cat_url

                                promos.append(self.make_promo(
                                    title=title,
                                    desc=desc,
                                    img=img_url,
                                    href=promo_url,
                                    category=category_name,
                                ))
                            except Exception:
                                continue
                    except Exception as e:
                        print(f"    [Itaú] Category {cat_url} error: {e}")
                        continue

            finally:
                browser.close()

        return promos


# ═══════════════════════════════════════════════════════════════════
#  CONTINENTAL  — https://www.bancontinental.com.py/#/club-continental/comercios
#  Angular SPA — requires Playwright
# ═══════════════════════════════════════════════════════════════════
class ContinentalScraper(ScraperBase):
    bank_id = "continental"
    bank_name = "Banco Continental"
    bank_url = "https://www.bancontinental.com.py/#/club-continental/comercios"
    bank_color = "#3B82F6"
    bank_short = "Continental"

    def scrape_api(self) -> list[dict]:
        api_candidates = [
            "https://www.bancontinental.com.py/api/club-continental/comercios",
            "https://www.bancontinental.com.py/api/v1/comercios",
            "https://www.bancontinental.com.py/api/beneficios",
        ]
        for url in api_candidates:
            try:
                data = self.fetch_json(url, timeout=10)
                if isinstance(data, list) and data:
                    promos = []
                    for item in data:
                        title = item.get("nombre") or item.get("title", "")
                        if title and len(title) > 2:
                            desc = item.get("descripcion") or item.get("description")
                            # Handle img field: might be a dict or string
                            img_raw = item.get("imagen") or item.get("image", "")
                            if isinstance(img_raw, dict):
                                img = img_raw.get("url", "")
                            else:
                                img = img_raw if isinstance(img_raw, str) else ""
                            href = item.get("url") or item.get("link", "")
                            # Only keep if we have a non-empty description or href (to filter out category-only entries)
                            if (desc is not None and desc.strip() != '') or (href is not None and href.strip() != ''):
                                promos.append(self.make_promo(
                                    title=title,
                                    desc=desc.strip() if desc else None,
                                    img=img,
                                    href=href,
                                ))
                    if promos:
                        return promos
            except Exception:
                continue
        raise NotImplementedError("No Continental API found")

    def scrape_html(self) -> list[dict]:
        raise NotImplementedError("Continental is a SPA")

    def scrape_playwright(self, scroll: bool = False) -> list[dict]:
        if not HAS_PLAYWRIGHT:
            raise RuntimeError("Playwright not installed")

        promos: list[dict] = []
        api_responses: list[dict] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                locale="es-PY",
                viewport={"width": 1440, "height": 900},
            )
            page = ctx.new_page()
            if stealth_sync:
                stealth_sync(page)

            def handle_response(response):
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        api_responses.append({"url": response.url, "data": response.json()})
                except Exception:
                    pass

            page.on("response", handle_response)

            try:
                page.goto(self.bank_url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(8_000)

                # Parse intercepted API responses
                for resp in api_responses:
                    data = resp["data"]
                    items = data if isinstance(data, list) else data.get("data", data.get("items", data.get("comercios", [])))
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict):
                                title = item.get("nombre") or item.get("title") or item.get("comercio") or ""
                                if title and len(title) > 2:
                                    desc = item.get("descripcion") or item.get("description")
                                    # Handle img field: might be a dict or string
                                    img_raw = item.get("imagen") or item.get("image", "")
                                    if isinstance(img_raw, dict):
                                        img = img_raw.get("url", "")
                                    else:
                                        img = img_raw if isinstance(img_raw, str) else ""
                                    href = item.get("url") or item.get("link", "")
                                    # Only keep if we have a non-empty description or href (to filter out category-only entries)
                                    if (desc is not None and desc.strip() != '') or (href is not None and href.strip() != ''):
                                        promos.append(self.make_promo(
                                            title=title,
                                            desc=desc.strip() if desc else None,
                                            img=img,
                                            href=href,
                                            category=item.get("categoria") or item.get("category"),
                                        ))

                if not promos:
                    html = page.content()
                    self._save_html_sample(html, "playwright")
                    soup = BeautifulSoup(html, "html.parser")
                    promos = self._parse_common(soup)

            finally:
                browser.close()

        return promos


# ═══════════════════════════════════════════════════════════════════
#  PERSONAL PAY  — https://www.personalpay.com.py/beneficios
#  SPA + Cloudflare protection
# ═══════════════════════════════════════════════════════════════════
class PersonalPayScraper(ScraperBase):
    bank_id = "personalpay"
    bank_name = "Personal Pay"
    bank_url = "https://www.personalpay.com.py/beneficios"
    bank_color = "#8B5CF6"
    bank_short = "PersonalPay"

    def scrape_api(self) -> list[dict]:
        api_candidates = [
            "https://www.personalpay.com.py/api/beneficios",
            "https://www.personalpay.com.py/api/v1/beneficios",
        ]
        for url in api_candidates:
            try:
                data = self.fetch_json(url, timeout=10)
                if isinstance(data, list) and data:
                    promos = []
                    for item in data:
                        title = item.get("titulo") or item.get("title", "")
                        if title:
                            desc = item.get("descripcion") or item.get("description")
                            img = item.get("imagen") or item.get("image", "")
                            href = item.get("url") or item.get("link", "")
                            # Solo considerar como promoción si tiene al menos título y alguno de: descripción, imagen o enlace
                            if desc or img or href:
                                promos.append(self.make_promo(
                                    title=title,
                                    desc=desc,
                                    img=img,
                                    href=href,
                                ))
                    if promos:
                        return promos
            except Exception:
                continue
        raise NotImplementedError("No PersonalPay API found")

    def scrape_html(self) -> list[dict]:
        # PersonalPay blocks HTTP requests with Cloudflare
        html = self.fetch_html()
        self._save_html_sample(html, "html")
        if "cloudflare" in html.lower() or "challenge" in html.lower():
            raise RuntimeError("Cloudflare protection detected")
        soup = BeautifulSoup(html, "html.parser")
        return self._parse_common(soup)

    def scrape_playwright(self, scroll: bool = False) -> list[dict]:
        if not HAS_PLAYWRIGHT:
            raise RuntimeError("Playwright not installed")

        promos: list[dict] = []
        api_responses: list[dict] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                locale="es-PY",
                viewport={"width": 1440, "height": 900},
            )
            page = ctx.new_page()
            if stealth_sync:
                stealth_sync(page)

            def handle_response(response):
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct and any(
                        kw in response.url.lower()
                        for kw in ["beneficio", "promo", "descuento"]
                    ):
                        api_responses.append({"url": response.url, "data": response.json()})
                except Exception:
                    pass

            page.on("response", handle_response)

            try:
                page.goto(self.bank_url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(10_000)  # Extra time for Cloudflare challenge

                for resp in api_responses:
                    data = resp["data"]
                    items = data if isinstance(data, list) else data.get("data", data.get("items", []))
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict):
                                title = item.get("titulo") or item.get("title") or item.get("nombre") or ""
                                if title and len(title) > 2:
                                    desc = item.get("descripcion") or item.get("description")
                                    img = item.get("imagen") or item.get("image", "")
                                    href = item.get("url") or item.get("link", "")
                                    # Solo considerar como promoción si tiene al menos título y alguno de: descripción, imagen o enlace
                                    if desc or img or href:
                                        promos.append(self.make_promo(
                                            title=title,
                                            desc=desc,
                                            img=img,
                                            href=href,
                                            category=item.get("categoria") or item.get("category"),
                                        ))

                if not promos:
                    html = page.content()
                    self._save_html_sample(html, "playwright")
                    # Check for Cloudflare block
                    if "challenge" in html.lower() and len(html) < 5000:
                        raise RuntimeError("Cloudflare challenge not bypassed")
                    soup = BeautifulSoup(html, "html.parser")
                    promos = self._parse_common(soup)

            finally:
                browser.close()

        return promos