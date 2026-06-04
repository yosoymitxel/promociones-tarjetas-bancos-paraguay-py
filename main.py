from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from scraper_modules import SCRAPERS
from analysis import analyze_promo


def deduplicate(promos: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    unique: list[dict] = []
    for p in promos:
        key = (p["bankId"], p["title"].lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def generate_html(all_promos: list[dict], run_stats: dict) -> str:
    template_path = Path("viewer_template.html")
    if not template_path.exists():
        raise FileNotFoundError("viewer_template.html not found in the workspace")

    template = template_path.read_text()
    html = template.replace("__PROMOS_JSON__", json.dumps(all_promos, ensure_ascii=False))
    html = html.replace("__STATS_JSON__",  json.dumps(run_stats,   ensure_ascii=False))
    html = html.replace("__TIMESTAMP__",   datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
    return html


def main() -> None:
    parser = argparse.ArgumentParser(description="Paraguayan Bank Promotions Scraper")
    parser.add_argument(
        "--skip-playwright",
        action="store_true",
        help="Skip scrapers that require Playwright",
    )
    args = parser.parse_args()

    print("=" * 52)
    print("PROMOSCRAPER PY — ORCHESTRATOR PIPELINE STARTING")
    print(f"Timestamp: {datetime.now().isoformat()}")
    if args.skip_playwright:
        print("Option: --skip-playwright active.")
    print("=" * 52)

    all_promos: list[dict] = []
    run_stats:  dict[str, dict] = {}

    for bank_id, ScraperClass in SCRAPERS.items():
        print(f"\n[{ScraperClass.bank_short}] Running scraper…")

        # requires_playwright is a class attribute on ScraperBase (default False).
        # SPA scrapers set it to True, so we no longer need a hard-coded list here.
        if args.skip_playwright and ScraperClass.requires_playwright:
            print(f"[{ScraperClass.bank_short}] SKIPPED: --skip-playwright active.")
            run_stats[bank_id] = {"status": "skipped", "count": 0}
            continue

        try:
            scraper = ScraperClass()
            promos  = scraper.scrape()

            enriched = [analyze_promo(p) for p in promos]
            all_promos.extend(enriched)

            print(f"[{ScraperClass.bank_short}] SUCCESS: {len(enriched)} promos extracted.")
            run_stats[bank_id] = {
                "status": "success" if enriched else "no_data",
                "count":  len(enriched),
            }
        except Exception as exc:
            print(f"[{ScraperClass.bank_short}] FAILED: {type(exc).__name__}: {exc}")
            run_stats[bank_id] = {
                "status": "failed",
                "error":  f"{type(exc).__name__}: {exc}",
                "count":  0,
            }

    original_len = len(all_promos)
    all_promos   = deduplicate(all_promos)
    dedup_count  = original_len - len(all_promos)

    print(f"\n{'=' * 52}")
    print(
        f"Pipeline complete: {len(all_promos)} unique promotions "
        f"({dedup_count} duplicates removed)"
    )
    print("=" * 52)

    output_dir = Path("./")

    json_path = output_dir / "promos.json"
    json_path.write_text(json.dumps(all_promos, ensure_ascii=False, indent=2))
    print(f"Saved JSON → {json_path.absolute()}")

    html_content = generate_html(all_promos, run_stats)
    html_path    = output_dir / "index.html"
    html_path.write_text(html_content)
    print(f"Saved HTML → {html_path.absolute()}")
    print("All tasks finished successfully.")


if __name__ == "__main__":
    main()
