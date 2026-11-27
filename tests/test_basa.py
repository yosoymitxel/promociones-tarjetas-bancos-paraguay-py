import unittest
from unittest.mock import patch

from scraper_modules.base import ScraperBase
from scraper_modules.scrapers import BASAScraper


class BASAFallbackTests(unittest.TestCase):
    def test_pdf_enrichment_timeout_keeps_html_promotions(self):
        scraper = BASAScraper()
        html_promos = [{"title": "Promo HTML", "bankId": "basa"}]

        with (
            patch("scraper_modules.scrapers.HAS_PLAYWRIGHT", True),
            patch.object(ScraperBase, "scrape", return_value=html_promos),
            patch.object(
                scraper,
                "_enrich_with_pdfs",
                side_effect=TimeoutError("BASA page navigation timed out"),
            ),
        ):
            result = scraper.scrape()

        self.assertEqual(result, html_promos)


if __name__ == "__main__":
    unittest.main()
