"""Separación de comercios desde PDFs y listas textuales de locales adheridos."""
import io
import re
import unicodedata

import httpx

BULLET = re.compile(r'^\s*[▪•■●]\s*(.+)$')
CARD = re.compile(r'Beneficios?\s+(?:con\s+la\s+|para\s+)?([^:\n]{3,60}):[\s\S]{0,160}?(\d{1,2})\s?%')
DAYS = re.compile(r'Vigencia:\s*([^\n.]+)')
_AFFILIATED_LABEL = re.compile(r'\blocales\s+adheridos\s*:\s*(.+)$', re.I | re.S)

# Catálogo de nombres tomados del listado de Paseo La Galería. Se usa para
# tokenizar el texto concatenado sin cortar nombres compuestos a ciegas.
_STORE_CATALOG = (
    ("ALDO", ("ALDO",)),
    ("BERTONI", ("BERTONI",)),
    ("BIRKENSTOCK", ("BIRKENSTOCK",)),
    ("EL MERCADILLO", ("EL MERCADILLO",)),
    ("GAP", ("GAP",)),
    ("MOSS", ("MOSS",)),
    ("UNDER ARMOUR", ("UNDER ARMOUR",)),
    ("VERONICA WILLIGS", ("VERONICA WILLIGS",)),
    ("ALEMANIA CELL", ("ALEMANIA CELL",)),
    ("BRAUN", ("BRAUN",)),
    ("CALVIN KLEIN", ("CALVIN KLEIN",)),
    ("CASA AMERICANA", ("CASA AMERICANA",)),
    ("CUNA BELLA", ("CUNA BELLA",)),
    ("HERING", ("HERING",)),
    ("HIGH LOW", ("HIGH LOW", "HIGH AND LOW")),
    ("ISDIN", ("ISDIN",)),
    ("JOYERIA ARMELE", ("JOYERIA ARMELE", "ARMELE")),
    ("MAC", ("MAC",)),
    ("MANGO", ("MANGO",)),
    ("ORAL B", ("ORAL B",)),
    ("PALUPIA", ("PALUPIA",)),
    ("PARFOIS", ("PARFOIS",)),
    ("PILAR", ("PILAR", "TIENDAS PILAR")),
    ("TL SPORT & OUTDOORS", ("TL SPORT & OUTDOORS",)),
    ("TOMMY HILFIGER", ("TOMMY HILFIGER",)),
    ("VENDOME RELOJERIA", ("VENDOME RELOJERIA", "VENDOME JOYERIA")),
    ("AEROPOSTALE", ("AEROPOSTALE",)),
    ("APHRODITE", ("APHRODITE",)),
    ("CASA MARIA", ("CASA MARIA",)),
    ("CAT", ("CAT",)),
    ("CHAMPS ELYSEÉS", ("CHAMPS ELYSEES",)),
    ("COLE HAAN", ("COLE HAAN",)),
    ("COLUMBIA", ("COLUMBIA",)),
    ("CROCS", ("CROCS",)),
    ("DENOIR", ("DENOIR",)),
    ("ENEACHE", ("ENEACHE",)),
    ("FUSCHIA", ("FUSCHIA",)),
    ("INDIAN EMPORIUM", ("INDIAN EMPORIUM",)),
    ("JOSEFINA", ("JOSEFINA",)),
    ("KERASTASE", ("KERASTASE",)),
    ("LUPO", ("LUPO",)),
    ("MARIE MARIE", ("MARIE MARIE",)),
    ("MATCH", ("MATCH",)),
    ("MAYBELLINE", ("MAYBELLINE",)),
    ("MUAR", ("MUAR",)),
    ("NEW BALANCE", ("NEW BALANCE",)),
    ("NINE WEST", ("NINE WEST",)),
    ("ODETTE", ("ODETTE",)),
    ("OPTICA VISION", ("OPTICA VISION",)),
    ("PIERRE LANNIER", ("PIERRE LANNIER",)),
    ("PLANET TOY", ("PLANET TOY", "PLANET TOYS")),
    ("PULSAK", ("PULSAK",)),
    ("PUMA", ("PUMA",)),
    ("RND", ("RND",)),
    ("ROCHESTER", ("ROCHESTER",)),
    ("RONDINA", ("RONDINA",)),
    ("SCALA", ("SCALA",)),
    ("SKECHERS", ("SKECHERS", "SKETCHERS")),
    ("SPORT HOUSE", ("SPORT HOUSE",)),
    ("TIMBERLAND", ("TIMBERLAND",)),
    ("TOTTO", ("TOTTO",)),
    ("VERDAD CONSECUENCIA", ("VERDAD CONSECUENCIA", "VERDAD O CONSECUENCIA")),
    ("WRANGLER - LEE", ("WRANGLER LEE", "LEE WRANGLER")),
    ("GNC", ("GNC",)),
    ("VERNIER", ("VERNIER", "JEAN VERNIER")),
    ("BIBI", ("BIBI",)),
)

def _tokens(value: str) -> tuple[str, ...]:
    plain = unicodedata.normalize("NFKD", value)
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    plain = plain.upper().replace("&", " AND ")
    return tuple(re.findall(r"[A-Z0-9]+", plain))


_STORE_ALIASES = sorted(
    (
        (_tokens(alias), display)
        for display, aliases in _STORE_CATALOG
        for alias in aliases
    ),
    key=lambda item: (len(item[0]), sum(map(len, item[0]))),
    reverse=True,
)


def parse_affiliated_stores(value: str) -> list[str]:
    """Reconoce el listado concatenado solo si puede segmentar todos sus tokens."""
    tokens = _tokens(value)
    if not tokens:
        return []

    stores: list[str] = []
    position = 0
    while position < len(tokens):
        for alias, display in _STORE_ALIASES:
            end = position + len(alias)
            if tokens[position:end] == alias:
                stores.append(display)
                position = end
                break
        else:
            # Un nombre desconocido invalida la separación completa: no inventar cortes.
            return []

    return stores


def extract_affiliated_stores(description: str | None) -> tuple[str | None, list[str]]:
    """Extrae y limpia el bloque final 'Locales adheridos:' de una descripción."""
    if not description:
        return description, []

    match = _AFFILIATED_LABEL.search(description)
    if not match:
        return description, []

    stores = parse_affiliated_stores(match.group(1))
    if len(stores) < 3:
        return description, []

    clean_description = description[:match.start()].rstrip(" \t\r\n.;")
    return clean_description or None, stores


def _slug(value: str) -> str:
    return "-".join(_tokens(value)).lower()


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
        # Itaú publica los locales en texto corrido dentro de las bases, no en PDF.
        if p.get('bankId') == 'itau':
            clean_desc, names = extract_affiliated_stores(p.get('desc'))
            if names:
                parent = dict(p)
                parent['desc'] = clean_desc
                parent['affiliated_stores'] = names
                out.append(parent)

                for name in names:
                    child = dict(parent)
                    child['id'] = f"{p['id']}-store-{_slug(name)}"
                    child['title'] = name
                    child['group'] = p.get('title')
                    child['parent_id'] = p.get('id')
                    child['img'] = ''  # share_logos() intenta reutilizar el logo de otro banco
                    child.pop('affiliated_stores', None)
                    out.append(child)

                print(f"[explode] {p.get('title')}: {len(names)} locales Itaú")
                continue

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
