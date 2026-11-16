"""Actualiza todo de una vez: PromoPY, el panel y GNB (este último desde tu PC).

    python actualizar.py

Necesita la CLI de GitHub (`gh auth login` una vez) y git con permiso de subir.
"""
import subprocess
import sys

REPOS = ["yosoymitxel/promociones-tarjetas-bancos-paraguay-py", "yosoymitxel/Web-scrapping"]

print("GNB (desde esta PC)…")
subprocess.run([sys.executable, "gnb_local.py"], check=False)
for repo in REPOS:
    r = subprocess.run(["gh", "api", "-X", "POST", f"repos/{repo}/actions/workflows/update.yml/dispatches", "-f", "ref=main"])
    print(("✓ " if r.returncode == 0 else "✗ ") + repo)
print("Listo: en ~10 min están los datos nuevos.")
