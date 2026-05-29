"""
Text analysis for promotion data enrichment.

Extracts discount percentages, days of the week, installment counts,
and auto-categorizes promotions based on title/description keywords.
"""
from __future__ import annotations

import re


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
    """Extract days of the week mentioned in the text."""
    text = f"{title} {desc or ''}".upper()
    days: set[str] = set()

    # Check full day names and phrases first
    for key, name in _DAY_MAP.items():
        if key in text:
            days.add(name)

    # Check short-form with word boundaries (avoid false matches)
    for key, name in _SHORT_DAYS.items():
        if re.search(rf'\b{key}\b', text):
            days.add(name)

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
_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("🍽️ Gastronomía", [
        "restaurant", "restaurante", "gastro", "comida", "hamburgues",
        "pizza", "café", "cafeter", "bar ", "resto", "parrilla",
        "sushi", "sbarro", "don vito", "fork", "pollos",
    ]),
    ("🛒 Supermercados", [
        "supermercado", "super ", "súper", "mayorista",
    ]),
    ("💊 Salud", [
        "farmac", "salud", "clínica", "clinic", "hospital", "sanatorio",
        "odonto", "dental", "óptic", "optic", "rapidoc", "drugstore",
        "veterinar",
    ]),
    ("🏋️ Fitness", [
        "gym", "fitness", "spa", "deport", "sport",
    ]),
    ("📱 Tecnología", [
        "electr", "tech", "celular", "cell", "samsung", "motorola",
        "istore", "ishop", "compu", "novatech", "radioshack",
    ]),
    ("👗 Moda", [
        "moda", "ropa", "zapato", "calzado", "tienda", "boutique",
        "joya", "relojer", "crocs", "nike", "new balance", "timberland",
        "cole haan",
    ]),
    ("🏠 Hogar", [
        "hogar", "mueble", "deco", "ferret", "construct",
        "electrodom", "colchon", "sommier",
    ]),
    ("🎓 Educación", [
        "colegio", "universidad", "educativ", "instituto", "academ",
    ]),
    ("🏨 Viajes & Hoteles", [
        "hotel", "viaje", "travel", "turismo", "resort",
        "aerolín", "vuelo",
    ]),
    ("⛽ Combustible", [
        "copetrol", "petromax", "petrobras", "combustible", "enex",
    ]),
    ("🎬 Entretenimiento", [
        "cine", "cinemark", "show", "stand up", "teatro", "evento",
    ]),
    ("💳 Financiero", [
        "cuotas", "reintegro", "cashback", "sorteo",
    ]),
]


def extract_category(title: str, desc: str | None) -> str | None:
    """Auto-categorize a promotion based on keyword matching."""
    text = f"{title} {desc or ''}".lower()

    for category, keywords in _CATEGORY_RULES:
        for kw in keywords:
            if kw in text:
                return category

    return None


# ─── Validity Extraction ──────────────────────────────────────────
def extract_validity(title: str, desc: str | None) -> str | None:
    """Extract a validity string or date range from text (e.g., 'Del 01 de enero al 31 de diciembre del 2026')."""
    text = f"{title} {desc or ''}"
    
    # Spanish months list
    months_pat = r'(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)'
    
    # Typical date patterns in Paraguayan bank promos
    patterns = [
        # Del XX de mes al YY de mes de AAAA
        r'(?i)(del\s+\d+\s+de\s+' + months_pat + r'\s+(?:al|del|a)\s+\d+\s+de\s+' + months_pat + r'(?:\s+del|\s+de)?\s+\d{4})',
        # Del XX de mes de AAAA al YY de mes de BBBB
        r'(?i)(del\s+\d+\s+de\s+' + months_pat + r'(?:\s+del|\s+de)?\s+\d{4}\s+(?:al|del|a)\s+\d+\s+de\s+' + months_pat + r'(?:\s+del|\s+de)?\s+\d{4})',
        # Válido hasta el XX de mes de AAAA
        r'(?i)(válido\s+hasta\s+el\s+\d+\s+de\s+' + months_pat + r'(?:\s+del|\s+de)?\s+\d{4})',
        # Hasta el XX de mes de AAAA
        r'(?i)(hasta\s+el\s+\d+\s+de\s+' + months_pat + r'(?:\s+del|\s+de)?\s+\d{4})',
        # XX/XX/XXXX al YY/YY/XXXX
        r'(\d{2}/\d{2}/\d{4}\s+(?:al|a|-)\s+\d{2}/\d{2}/\d{4})',
        # Vigencia: XX/XX/XXXX
        r'(?i)(vigencia:?\s*\d{2}/\d{2}/\d{4}(?:\s+al\s+\d{2}/\d{2}/\d{4})?)',
    ]
    
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            # Clean up multiple whitespaces
            res = re.sub(r'\s+', ' ', m.group(1)).strip()
            # Strip trailing period if present
            if res.endswith('.'):
                res = res[:-1]
            return res[0].upper() + res[1:]
            
    return None


# ─── Main enrichment function ────────────────────────────────────
def analyze_promo(promo: dict) -> dict:
    """Enrich a promo dict with extracted discount, days, installments, category, and validity."""
    title = promo.get("title", "")
    desc = promo.get("desc")

    promo["discount_percent"] = extract_discount(title, desc)
    promo["days"] = extract_days(title, desc)
    promo["installments"] = extract_installments(title, desc)
    promo["validity"] = extract_validity(title, desc)

    # Only set category if not already present
    if not promo.get("category"):
        promo["category"] = extract_category(title, desc)

    return promo