"""Baja los beneficios de Banco GNB desde tu PC y los sube al repo.

GNB bloquea los servidores de GitHub, así que la actualización automática no puede leerlos.
Correlo cuando quieras (o programalo una vez por semana):

    python gnb_local.py          # baja y sube
    python gnb_local.py --no-push

La actualización diaria usa gnb_raw.json mientras tenga menos de 10 días.
"""
import json
import subprocess
import sys
import urllib.request

URL = "https://www.beneficiosbancognb.com.py/apis/rewards/rewards/v1/benefits/benefits?pageSize=999"
req = urllib.request.Request(URL, headers={
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.beneficiosbancognb.com.py/v2/beneficios/categorias",
})
with urllib.request.urlopen(req, timeout=30) as r:
    data = json.load(r)
items = data.get("data", data) if isinstance(data, dict) else data
print(f"GNB: {len(items)} beneficios")
if not items:
    sys.exit("Sin datos: no se guarda nada.")
with open("gnb_raw.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
if "--no-push" not in sys.argv:
    subprocess.run(["git", "pull", "--rebase", "-q"], check=True)
    subprocess.run(["git", "add", "gnb_raw.json"], check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode:
        subprocess.run(["git", "commit", "-qm", "GNB: beneficios desde PC"], check=True)
        subprocess.run(["git", "push", "-q"], check=True)
        print("Subido. La próxima actualización de PromoPY lo incluye.")
    else:
        print("Sin cambios.")
