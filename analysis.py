"""
Text analysis for promotion data enrichment.

Extracts discount percentages, days of the week, installment counts,
and auto-categorizes promotions based on title/description keywords.
"""
from __future__ import annotations

import re
from datetime import date


# ─── Discount ──────────────────────────────────────────────────────
def extract_discount(title: str, desc: str | None) -> int | None:
    """Extract the most prominent discount percentage from text."""
    text = f"{title} {desc or ''}"

    # Patterns like "20% OFF", "Hasta 30%", "20% de descuento", "20% reintegro"
    patterns = [
        r'(\d+)\s*%\s*(?:off|descuento|dto|reintegro|cashback|dscto)',
        r'hasta\s+(\d+)\s*%',
        r'(\d+)\s*%',
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 100:
                return val

    return None


# ─── Days ──────────────────────────────────────────────────────────
_DAY_MAP = {
    "LUNES": "Lunes",
    "MARTES": "Martes",
    "MIÉRCOLES": "Miércoles",
    "MIERCOLES": "Miércoles",
    "JUEVES": "Jueves",
    "VIERNES": "Viernes",
    "SÁBADO": "Sábado",
    "SABADO": "Sábado",
    "DOMINGO": "Domingo",
    "TODOS LOS DÍAS": "Todos",
    "TODOS LOS DIAS": "Todos",
    "TODA LA SEMANA": "Todos",
}

# Short-form days as individual word boundaries
_SHORT_DAYS = {
    "LUN": "Lunes",
    "MAR": "Martes",
    "MIE": "Miércoles",
    "JUE": "Jueves",
    "VIE": "Viernes",
    "SAB": "Sábado",
    "DOM": "Domingo",
}


def extract_days(title: str, desc: str | None) -> list[str]:
    """Días de la promo principal: lo que va después de "Además," suele ser otro beneficio
    (ej. "Los miércoles 20%... Además, todos los días: cuotas")."""
    # El día va al principio; más abajo hay direcciones ("Santo Domingo") y letra chica
    text = f"{title} {(desc or '')[:600]}".upper()
    return _days(re.split(r'\bADEM[AÁ]S\b', text)[0]) or _days(text)


def _days(text: str) -> list[str]:
    days: set[str] = set()

    # Check full day names and phrases first
    for key, name in _DAY_MAP.items():
        if key in text:
            days.add(name)

    # Check short-form with word boundaries (avoid false matches)
    for key, name in _SHORT_DAYS.items():
        if re.search(rf'\b{key}\b', text):
            days.add(name)

    # Rangos: "lunes a jueves" → lunes, martes, miércoles, jueves
    order = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    norm = lambda w: _DAY_MAP.get(w) or _DAY_MAP[w[:-1]]  # "SÁBADOS" → "SÁBADO"
    for x, y in re.findall(r'(LUNES|MARTES|MI[EÉ]RCOLES|JUEVES|VIERNES|S[AÁ]BADOS?)\s+(?:A|AL)\s+(MARTES|MI[EÉ]RCOLES|JUEVES|VIERNES|S[AÁ]BADOS?|DOMINGOS?)', text):
        i, j = order.index(norm(x)), order.index(norm(y))
        days.update(order[i:j + 1])

    # If "Todos" is found, just return that
    if "Todos" in days:
        return ["Todos"]

    return sorted(days)


# ─── Installments ─────────────────────────────────────────────────
def extract_installments(title: str, desc: str | None) -> int | None:
    """Extract number of installments (cuotas) from text."""
    text = f"{title} {desc or ''}".upper()

    patterns = [
        r'(\d+)\s*(?:CUOTAS?|CSI)',
        r'(?:HASTA\s+)?(\d+)\s*(?:CUOTAS?)',
        r'(\d+)\s*(?:PAGOS?|MESES)',
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 2 <= val <= 60:
                return val

    # Check for "sin interés" / "cuotas sin intereses" without specific number
    if re.search(r'CUOTAS?\s+SIN\s+INTER[EÉ]S', text, re.IGNORECASE):
        return 0  # 0 means "cuotas sin interés" (unspecified count)

    return None


# ─── Category ─────────────────────────────────────────────────────
# Rubros fijos: las etiquetas de cada banco ("Días GNB", "Verano", "Itaú Personal Bank",
# "MasterCard Debit"...) son campañas, no rubros, y se reclasifican por palabras clave.
_CATEGORY_RULES: list[tuple[str, str]] = [
    ("🛒 Supermercados", r"supermercad|s[uú]per\b|mayorista|hipermercad|contimarket|biggie|stock\b|superseis|casa rica|delimarket|salemma|real\b|areté|arete|pulsak|\bmarket\b|almac[eé]n|alimentos|distribuidora|atacado"),
    ("⛽ Combustible", r"copetrol|petromax|petrobras|combustible|\benex\b|\bshell\b|puma energy|estaci[oó]n de servicio"),
    ("💊 Salud y belleza", r"farma|salud|cl[ií]nica|hospital|sanatorio|odonto|dental|[oó]ptic|laborator|belleza|peluquer|barber|barbas|est[eé]tica|cosm[eé]t|perfum|spa\b|masaje|u[ñn]as|isdin|auditiv|nutri|suplement|dermat|m[eé]dic|psic|kinesi|fisio"),
    ("🍽️ Gastronomía", r"restaur|resto\b|gastro|comida|hamburgues|burger|pizz|caf[eé]|cafeter|\bbar\b|bares|parrill|sushi|helad|panader|confiter|pastel|delivery|pedidosya|starbucks|juan valdez|mostaza|bellini|lomit|empanad|grill|cervec|brew|bistr|kfc|sbarro|don vito|rostiser|porchetta|bocatta|chicken|pollo|asado|cocina|sabores|taberna|pub\b|food"),
    ("🏋️ Deportes y fitness", r"\bgym|gimnas|fitness|\bfit\b|training|getfit|body ?center|crossfit|deport|sport|bicicl|outdoor|pilates|yoga"),
    ("📱 Tecnología", r"electr[oó]nic|tecnolog|celular|samsung|motorola|apple|istore|ishop|inform[aá]tic|computa|gamer|novatech|radioshack|plataforma|streaming|internet|telefon"),
    ("🏠 Hogar", r"hogar|mueble|decora|ferreter|construc|electrodom|colch[oó]n|sommier|ashley|cer[aá]mic|sanitari|pintur|ilumina|luminot|jard[ií]n|riego|aceros|herramient|alfombra|cortina|bazar|living|cocinas|aberturas|vidrier|piscin|maquin"),
    ("🚗 Autos", r"\bauto|automot|motor|neum[aá]tic|taller|repuesto|lubric|concesionar|lavadero|car ?wash|cubierta|tire\b|toyot|nissan|kia\b|hyundai|chevrolet|moto"),
    ("👗 Moda", r"\bmoda|ropa|indumentar|zapat|calzad|boutique|joy[aei]|relojer|crocs|nike|adidas|skechers|lacoste|new balance|timberland|jean|lencer|cartera|accesorio|sneaker|novias|telas|springfield|brooksfield|optica|anteojo|vestir|tienda de ropa|multimarcas|sastrer"),
    ("🧸 Niños", r"\bni[ñn]os|kids|juguet|beb[eé]|infantil|mam[aá]|mamissima"),
    ("🎓 Educación", r"colegio|universidad|educa|instituto|academ|idioma|librer|escolar|curso"),
    ("🏨 Viajes", r"hotel|viaje|travel|turismo|resort|aerol[ií]n|vuelo|pasaje|posada|caba[ñn]a"),
    ("🎬 Entretenimiento", r"cine|cinemark|entrada|\bshow|teatro|evento|concierto|mplay|juego|parque"),
    ("🐾 Mascotas y agro", r"veterinar|mascot|pet\b|agro|balancead|ganad|semilla|huerta|vivero"),
    ("💳 Servicios", r"seguro|pr[eé]stamo|billetera|megas|recarga|packs? de|pospago|whatsapp|compras en el exterior|fotograf|lavander|adelanto de efectivo|pago de servicios|ande\b|essap"),
]
_RE_RULES = [(c, re.compile(rx, re.I)) for c, rx in _CATEGORY_RULES]

# Etiquetas de origen que sí son rubros
_SOURCE_MAP = {
    "autoaccesorios": "🚗 Autos", "belleza y salud": "💊 Salud y belleza", "hogar": "🏠 Hogar",
    "indumentaria": "👗 Moda", "tecnología": "📱 Tecnología", "gastronomía": "🍽️ Gastronomía",
    "supermercados": "🛒 Supermercados", "niños": "🧸 Niños",
}

OTHER = "Otros"


def extract_category(title: str, desc: str | None, source: str | None = None) -> str:
    """Rubro por nombre del comercio; si no alcanza, la primera frase del detalle (el resto es letra chica)."""
    # Nombre del comercio y comienzo del detalle; la letra chica de abajo confunde
    head = re.sub(r'afinidad\s+\S+', '', (desc or "")[:300], flags=re.I)  # "Afinidad Farmacenter" es una tarjeta
    for text in (title or "", head):
        for cat, rx in _RE_RULES:
            if rx.search(text):
                return cat
    return _SOURCE_MAP.get((source or "").strip().lower(), OTHER)


# ─── Validity Extraction ──────────────────────────────────────────
_M = r'(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)'
_D = r'\d{1,2}\s+de\s+' + _M + r'(?:(?:\s+(?:de|del))?\s+\d{4})?'
_WD = r'(?:(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s+)?'
_VALIDITY_RES = [re.compile(x, re.I) for x in (
    r'(?:desde\s+el|del?)\s+' + _D + r'\s+(?:al|del|hasta(?:\s+el)?|a)\s+(?:el\s+)?' + _D,
    r'hasta\s+el\s+' + _WD + _D,
    r'\d{2}/\d{2}/\d{4}\s+(?:al|a|-)\s+\d{2}/\d{2}/\d{4}',
    r'vigencia:?\s*\d{2}/\d{2}/\d{4}',
    # Un solo día: "El miércoles 18 de noviembre", "Vigente el 18 de noviembre de 2026"
    r'\b(?:el|vigente\s+el|v[aá]lido\s+el|solo\s+el)\s+' + _WD + _D + r'(?!\s+(?:al|hasta|a)\b)',
)]
_SINGLE = _VALIDITY_RES[-1]
_MONTHS = {m: i for i, m in enumerate('enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre'.split(), 1)}
_MONTHS['setiembre'] = 9


def extract_validity(title: str, desc: str | None) -> str | None:
    """La primera vigencia del texto (la de la promo; las de abajo suelen ser de "Además...")."""
    text = f"{title} {desc or ''}"
    hits = [m for rx in _VALIDITY_RES if (m := rx.search(text))]
    if not hits:
        return None
    m = min(hits, key=lambda m: m.start())
    res = re.sub(r'\s+', ' ', m.group(0)).strip().rstrip('.')
    if m.re is _SINGLE:
        res = 'El ' + re.sub(r'^(el|vigente el|v[aá]lido el|solo el)\s+', '', res, flags=re.I)
    return res[0].upper() + res[1:]


def validity_dates(validity: str | None, today: date) -> list[date]:
    """Fechas de la vigencia; sin año, el de hoy."""
    out = []
    for d, mo, y in re.findall(r'(\d{1,2})\s+de\s+(' + _M + r')(?:(?:\s+(?:de|del))?\s+(\d{4}))?', validity or '', re.I):
        try:
            out.append(date(int(y or today.year), _MONTHS[mo.lower()], int(d)))
        except ValueError:
            pass
    for d, mo, y in re.findall(r'(\d{2})/(\d{2})/(\d{4})', validity or ''):
        try:
            out.append(date(int(y), int(mo), int(d)))
        except ValueError:
            pass
    # "Del 1 de diciembre al 31 de enero de 2027": el inicio va con el año anterior
    if len(out) == 2 and out[0] > out[1]:
        out[0] = out[0].replace(year=out[1].year - 1)
    return out


_DAY_NAMES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


# ─── Main enrichment function ────────────────────────────────────
def analyze_promo(promo: dict, today: date | None = None) -> dict:
    """Completa descuento, días, cuotas, rubro y vigencia; `expired` si la vigencia ya pasó."""
    today = today or date.today()
    title = promo.get("title", "")
    desc = promo.get("desc")

    promo["discount_percent"] = extract_discount(title, desc)
    promo["days"] = extract_days(title, desc)
    promo["installments"] = extract_installments(title, desc)
    promo["validity"] = extract_validity(title, desc)
    promo["category"] = extract_category(title, desc, promo.get("category"))

    dates = validity_dates(promo["validity"], today)
    if dates and not re.search(r'\d{4}', promo["validity"]):
        promo["validity"] += f" de {max(dates).year}"  # el visor necesita el año para calcular vencimiento
    if len(dates) == 1 and (promo["validity"] or "").startswith("El "):
        promo["days"] = [_DAY_NAMES[dates[0].weekday()]]  # un solo día, no "todos los días"
    promo["expired"] = bool(dates) and max(dates) < today
    return promo
