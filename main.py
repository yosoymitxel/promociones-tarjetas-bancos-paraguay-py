from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo
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


def share_logos(promos: list[dict]) -> None:
    """Sin imagen (BASA no publica logos): usa la del mismo comercio en otro banco."""
    key = lambda t: re.sub(r'[^a-z0-9]', '', re.split(r'\s+[-–(]', (t or '').lower())[0])
    logos = {key(p["title"]): p["img"] for p in promos if p.get("img") and len(key(p["title"])) > 2}
    for p in promos:
        if not p.get("img"):
            p["img"] = logos.get(key(p["title"]), "")


def generate_html(all_promos: list[dict], run_stats: dict) -> str:
    template_path = Path("viewer_template.html")
    if not template_path.exists():
        raise FileNotFoundError("viewer_template.html not found in the workspace")

    template = template_path.read_text()
    all_promos = [p for p in all_promos if not p.get("expired")]
    html = template.replace("__PROMOS_JSON__", json.dumps(all_promos, ensure_ascii=False))
    html = html.replace("__STATS_JSON__",  json.dumps(run_stats,   ensure_ascii=False))
    html = html.replace("__TIMESTAMP__",   datetime.now(ZoneInfo("America/Asuncion")).strftime("%d/%m/%Y %H:%M") + " (hora PY)")
    return optimize_html(html)


def optimize_html(html: str) -> str:
    """Compila JSX y Tailwind en la build: el navegador no baja Babel (~3 MB) ni genera CSS al cargar.

    Si falta Node o falla algo, deja la página como estaba (Babel y Tailwind por CDN).
    """
    import re
    import subprocess
    import tempfile

    m = re.search(r'<script type="text/babel"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return html
    try:
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "app.jsx").write_text(m.group(1))
            (d / "page.html").write_text(html)
            (d / "in.css").write_text("@tailwind base;@tailwind components;@tailwind utilities;")
            (d / "tw.config.js").write_text(
                "module.exports={content:['./page.html'],theme:{extend:{fontFamily:{sans:['Outfit','sans-serif'],mono:['Space Mono','monospace']}}}}"
            )
            run = lambda *a: subprocess.run(a, cwd=d, check=True, capture_output=True, text=True, timeout=180)
            js = run("npx", "-y", "esbuild@0.24.0", "app.jsx", "--loader:.jsx=jsx", "--jsx=transform", "--minify", "--target=es2019").stdout
            run("npx", "-y", "tailwindcss@3.4.17", "-c", "tw.config.js", "-i", "in.css", "-o", "out.css", "--minify")
            css = (d / "out.css").read_text()
    except Exception as exc:  # sin Node: queda la versión con CDN
        print(f"[build] sin optimizar: {exc}")
        return html
    html = html[:m.start()] + "<script>" + js.replace("</script", "<\\/script") + "</script>" + html[m.end():]
    html = re.sub(r'\s*<script src="https://unpkg.com/@babel/standalone[^"]*"></script>', "", html)
    html = re.sub(r"\s*<script>\s*// Register a preset.*?</script>", "", html, flags=re.S)
    html = re.sub(r'\s*<script src="https://cdn.tailwindcss.com"></script>', "", html)
    html = re.sub(r"<script>\s*tailwind.config.*?</script>", lambda _: "<style>" + css + "</style>", html, flags=re.S)
    print(f"[build] JSX {len(js)//1024} KB y CSS {len(css)//1024} KB precompilados")
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

    # PDFs con listado de locales adheridos → una promo por local
    from scraper_modules.explode import explode
    all_promos = explode(all_promos)

    all_promos = [p for p in all_promos if not p.get("expired")]
    share_logos(all_promos)
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
