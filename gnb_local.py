"""Baja los beneficios de Banco GNB desde tu PC y los sube al repo.

GNB está detrás de Akamai: rechaza con 403 a curl, urllib y a Chrome headless.
Por eso hay que abrir un Chromium real (con ventana) y pedir la API desde la página.

Correlo cuando quieras (o programalo una vez por semana):

    python gnb_local.py          # baja y sube
    python gnb_local.py --no-push

La actualización diaria usa gnb_raw.json mientras tenga menos de 10 días.
"""
import json
import subprocess
import sys

PAGE = "https://www.beneficiosbancognb.com.py/v2/beneficios/categorias"
API = "/v2/apis/rewards/rewards/v1/benefits/benefits"
PAGE_SIZE = 100

FETCH_JS = """
async ({path, size, key}) => {
    const r = await fetch(`${path}?pageSize=${size}&paginationKey=${key}`, {
        headers: {Accept: 'application/json'},
    });
    if (!r.ok) throw new Error(`${r.status} ${path}`);
    return await r.json();
}
"""


def fetch_all(page) -> list[dict]:
    """La API corta en 100 por página y pagina con paginationKey, no con page=."""
    items: list[dict] = []
    seen: set = set()
    total_pages = 1
    key = 0
    while key < total_pages:
        data = page.evaluate(FETCH_JS, {"path": API, "size": PAGE_SIZE, "key": key})
        pagination = data.get("pagination") or {}
        total_pages = int(pagination.get("totalPages") or 1)
        for it in data.get("data") or []:
            if it.get("id") not in seen:
                seen.add(it["id"])
                items.append(it)
        key += 1
    return items


def main() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("Falta Playwright: pip install playwright && playwright install chromium")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        try:
            page = browser.new_context(locale="es-PY").new_page()
            page.goto(PAGE, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(6_000)
            if "Access Denied" in page.title():
                sys.exit("Akamai rechazó la conexión. Probá de nuevo en unos minutos.")
            items = fetch_all(page)
        finally:
            browser.close()

    print(f"GNB: {len(items)} beneficios")
    if not items:
        sys.exit("Sin datos: no se guarda nada.")

    with open("gnb_raw.json", "w", encoding="utf-8") as f:
        json.dump({"data": items}, f, ensure_ascii=False)

    if "--no-push" in sys.argv:
        return
    subprocess.run(["git", "pull", "--rebase", "-q"], check=True)
    subprocess.run(["git", "add", "gnb_raw.json"], check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode:
        subprocess.run(["git", "commit", "-qm", "GNB: beneficios desde PC"], check=True)
        subprocess.run(["git", "push", "-q"], check=True)
        print("Subido. La próxima actualización de PromoPY lo incluye.")
    else:
        print("Sin cambios.")


if __name__ == "__main__":
    main()
