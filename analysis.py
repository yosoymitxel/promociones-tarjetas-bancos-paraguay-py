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


# ─── Main enrichment function ────────────────────────────────────
def analyze_promo(promo: dict) -> dict:
    """Enrich a promo dict with extracted discount, days, installments, and category."""
    title = promo.get("title", "")
    desc = promo.get("desc")

    promo["discount_percent"] = extract_discount(title, desc)
    promo["days"] = extract_days(title, desc)
    promo["installments"] = extract_installments(title, desc)

    # Only set category if not already present
    if not promo.get("category"):
        promo["category"] = extract_category(title, desc)

    return promo