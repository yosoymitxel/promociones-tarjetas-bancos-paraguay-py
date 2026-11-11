"""PDFs con muchos comercios (ej. BASA "restaurantes.pdf"): una promo por local adherido.

Los bancos publican cada mes un PDF con "Locales Adheridos" en viñetas y un beneficio por tarjeta.
Una sola promo con el título del PDF no se encuentra al buscar "Bolsi"; acá se separa por local.
"""
import io
import re

import httpx

BULLET = re.compile(r'^\s*[▪•■●]\s*(.+)$')
CARD = re.compile(r'Beneficios?\s+(?:con\s+la\s+|para\s+)?([^:\n]{3,60}):[\s\S]{0,160}?(\d{1,2})\s?%')
DAYS = re.compile(r'Vigencia:\s*([^\n.]+)')


def _pdf_text(url: str) -> str:
    import pdfplumber
    r = httpx.get(url, timeout=30, follow_redirects=True, headers={'user-agent': 'Mozilla/5.0'})
    r.raise_for_status()
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        return '\n'.join(p.extract_text() or '' for p in pdf.pages)


def locales(text: str) -> list[str]:
    """Viñetas del bloque de locales; une las que siguen en la línea de abajo."""
    out, on = [], False
    for line in text.splitlines():
        if re.search(r'locales\s+adheridos|comercios\s+adheridos', line, re.I):
            on = True
            continue
        if not on:
            continue
        if re.search(r'beneficio', line, re.I):
            break
        # PDFs a varias columnas: varias viñetas en la misma línea
        parts = re.split(r'\s*[▪•■●\uf0a7\uf0b7]\s*', line)
        head, items = parts[0].strip(), [x.strip() for x in parts[1:] if x.strip()]
        if head and out and not re.search(r'para más|^\d+\.', head, re.I):
            out[-1] += ' ' + head
        out.extend(items)
    out = [re.sub(r'\s*\d{1,2}/\d{1,2}/\d{4}\)?', '', re.sub(r'\s*\(desde.*', '', re.sub(r'\*+', '', l))).strip() for l in out]
    return [l for l in out if 1 < len(l) < 80]


def explode(promos: list[dict]) -> list[dict]:
    out = []
    for p in promos:
        href = p.get('href') or ''
        if not href.lower().endswith('.pdf'):
            out.append(p)
            continue
        try:
            text = _pdf_text(href)
        except Exception as e:  # sin PDF queda la promo original
            print(f'[explode] {href}: {e}')
            out.append(p)
            continue
        names = locales(text)
        if len(names) < 3:
            out.append(p)
            continue
        cards = [f'{c.strip()} {pct}%' for c, pct in CARD.findall(text)]
        days = DAYS.search(text)
        print(f'[explode] {p.get("title")}: {len(names)} locales')
        for n in names:
            q = dict(p)
            q['id'] = f'{p["id"]}-{re.sub(r"[^a-z0-9]", "", n.lower())[:24]}'
            q['title'] = n
            q['group'] = p.get('title')
            if cards:
                q['cards'] = cards
                q['discount_percent'] = max(int(c.rsplit(' ', 1)[1][:-1]) for c in cards)
            if days:
                q['when'] = days.group(1).strip()
            out.append(q)
    return out
