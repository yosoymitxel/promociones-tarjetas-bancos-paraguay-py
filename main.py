from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from scraper_modules import SCRAPERS
from analysis import analyze_promo

# Try importing base to check Playwright presence
try:
    from scraper_modules.base import HAS_PLAYWRIGHT
except ImportError:
    HAS_PLAYWRIGHT = False


def deduplicate(all_promos: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for p in all_promos:
        # Deduplicate on bankId and title
        key = (p["bankId"], p["title"].lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def generate_html(all_promos: list[dict], run_stats: dict) -> str:
    # Read the viewer template
    template_path = Path("viewer_template.html")
    if not template_path.exists():
        raise FileNotFoundError("viewer_template.html was not found in the workspace")
    
    template = template_path.read_text()
    
    # Inject variables
    promos_json = json.dumps(all_promos, ensure_ascii=False)
    stats_json = json.dumps(run_stats, ensure_ascii=False)
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    html = template.replace("__PROMOS_JSON__", promos_json)
    html = html.replace("__STATS_JSON__", stats_json)
    html = html.replace("__TIMESTAMP__", timestamp)
    
    return html


def main():
    parser = argparse.ArgumentParser(description="Paraguayan Bank Promotions Scraper")
    parser.add_argument(
        "--skip-playwright",
        action="store_true",
        help="Skip running scrapers that require Playwright",
    )
    args = parser.parse_args()

    print("====================================================")
    print("PROMOSCRAPER PY — ORCHESTRATOR PIPELINE STARTING")
    print(f"Timestamp: {datetime.now().isoformat()}")
    if args.skip_playwright:
        print("Option: --skip-playwright active. Will skip Playwright scrapers.")
    print("====================================================")

    all_promos = []
    run_stats = {}

    for bank_id, ScraperClass in SCRAPERS.items():
        print(f"\n[{ScraperClass.bank_short}] Running scraper...")
        scraper = ScraperClass()

        # Decide whether to skip due to playwright restriction
        is_playwright_only = bank_id in ["gnb", "itau", "continental", "personalpay"]
        if args.skip_playwright and is_playwright_only:
            print(f"[{ScraperClass.bank_short}] SKIPPED: --skip-playwright option active.")
            run_stats[bank_id] = {"status": "skipped", "count": 0}
            continue

        try:
            # Execute scraper
            promos = scraper.scrape()

            # Process and enrich promos
            enriched_promos = []
            for p in promos:
                enriched = analyze_promo(p)
                enriched_promos.append(enriched)

            all_promos.extend(enriched_promos)
            print(f"[{ScraperClass.bank_short}] SUCCESS: {len(enriched_promos)} promos extracted.")
            run_stats[bank_id] = {
                "status": "success" if enriched_promos else "no_data",
                "count": len(enriched_promos),
            }

        except Exception as e:
            print(f"[{ScraperClass.bank_short}] FAILED: {type(e).__name__}: {e}")
            run_stats[bank_id] = {
                "status": "failed",
                "error": f"{type(e).__name__}: {str(e)}",
                "count": 0,
            }

    # Deduplicate accumulated promos
    original_len = len(all_promos)
    all_promos = deduplicate(all_promos)
    dedup_count = original_len - len(all_promos)

    print(f"\n====================================================")
    print(f"Pipeline Complete: {len(all_promos)} unique promotions collected ({dedup_count} duplicates removed)")
    print("====================================================")

    # Save output
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    json_path = output_dir / "promos.json"
    json_path.write_text(json.dumps(all_promos, ensure_ascii=False, indent=2))
    print(f"Saved JSON payload to {json_path.absolute()}")

    html_content = generate_html(all_promos, run_stats)
    html_path = output_dir / "index.html"
    html_path.write_text(html_content)
    print(f"Saved Standalone React/Tailwind page to {html_path.absolute()}")
    print("All tasks finished successfully.")


if __name__ == "__main__":
    main()