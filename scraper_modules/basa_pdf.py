"""
BASA alianzas PDF parser + content-hash cache.

Two responsibilities
--------------------
1. **Parse** a BASA Bases y Condiciones PDF into structured fields
   (validity, discount, days, installments, desc).

2. **Cache** parsed results keyed by URL + MD5 of the PDF bytes, so
   unchanged PDFs are never re-downloaded or re-parsed on subsequent runs.
   Only PDFs whose content actually changed on the server are processed.

Cache file
----------
reports/basa/pdf_cache.json
Schema:
  {
    "<pdf_url>": {
      "hash":       "<md5 hex>",
      "fetched_at": "<ISO datetime>",
      "parsed": {
        "desc":             "<str | null>",
        "validity":         "<str | null>",
        "discount_percent": <int | null>,
        "days":             ["Lunes", "Viernes", ...] | ["Todos"] | [],
        "installments":     <int | null>,   // 0 = sin interés
      }
    }
  }

How to use
----------
::

    from scraper_modules.basa_pdf import BASAPDFParser, PDFCache

    cache  = PDFCache()
    parser = BASAPDFParser()

    pdf_bytes = ...                          # raw bytes fetched via Playwright
    url       = "https://bancobasa.com.py/..."

    if cache.needs_parse(url, pdf_bytes):
        parsed = parser.parse(pdf_bytes, commerce_name="Avenida Autocentro")
        cache.store(url, pdf_bytes, parsed)
    else:
        parsed = cache.get(url)             # use cached result — no re-parse

    cache.save()                            # flush to disk (no-op if nothing changed)
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime
from pathlib import Path

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

# ── Pre-compiled patterns ──────────────────────────────────────────
# The BASA PDF structure is consistent across alianzas T&C documents:
#   • A header with the commerce name and "BASA" branding
#   • A "VIGENCIA" / "VÁLIDO" section with date range
#   • A benefit line: "X% de descuento" or "X cuotas sin interés"
#   • Days: "Lunes a Viernes", "Todos los días", etc.
#   • Card types: "Visa y Mastercard de crédito BASA"
#
# Adjust the patterns below if you encounter PDFs that don't match.

_RE_VIGENCIA = re.compile(
    r'(?:vigencia|v[aá]lid[ao](?:\s+(?:del?|desde|hasta))?|per[ií]odo)'
    r'[:\s]+(.{5,80}?)(?:\n|$)',
    re.IGNORECASE,
)
_RE_DATE_RANGE = re.compile(
    r'del?\s+\d{1,2}\s+de\s+\w+.{0,40}?al\s+\d{1,2}\s+de\s+\w+'
    r'(?:\s+de\s+\d{4})?',
    re.IGNORECASE,
)
_RE_DESCUENTO = re.compile(
    r'(\d+(?:[.,]\d+)?)\s*%\s*(?:de\s+)?(?:descuento|dto\.?|off)',
    re.IGNORECASE,
)
_RE_PERCENT_BARE = re.compile(r'(\d+(?:[.,]\d+)?)\s*%')   # fallback
_RE_CUOTAS = re.compile(
    r'(\d+)\s*cuotas?\s*(?:sin\s*inter[eé]s|0\s*%|a\s*tasa\s*0)?',
    re.IGNORECASE,
)
_RE_TARJETAS = re.compile(
    r'tarjetas?\s+(.{3,60}?)(?:\n|\.|basa)',
    re.IGNORECASE,
)

_DAY_NAMES_ES = {
    "lunes": "Lunes", "martes": "Martes",
    "mi[eé]rcoles": "Miércoles", "jueves": "Jueves",
    "viernes": "Viernes", "s[aá]bado": "Sábado", "domingo": "Domingo",
}

# Words that appear in every BASA PDF — not useful in the desc
_BOILERPLATE_FRAGMENTS = frozenset({
    "banco basa", "basa s.a.", "basa s. a.",
    "bases y condiciones", "bases  y  condiciones",
    "términos y condiciones", "terminos y condiciones",
    "ruc", "inscripto en el registro",
})


# ══════════════════════════════════════════════════════════════════
#  PDF Parser
# ══════════════════════════════════════════════════════════════════

class BASAPDFParser:
    """
    Parse a single BASA alianzas PDF into structured fields.

    Usage::

        parser = BASAPDFParser()
        result = parser.parse(pdf_bytes, "Avenida Autocentro")
        # → {"desc": "...", "validity": "...", "discount_percent": 20, ...}
    """

    def parse(self, pdf_bytes: bytes, commerce_name: str) -> dict:
        """
        Extract structured fields from a BASA T&C PDF.

        Parameters
        ----------
        pdf_bytes:      Raw bytes of the PDF file.
        commerce_name:  Commerce name used to filter boilerplate lines.

        Returns
        -------
        dict with keys: desc, validity, discount_percent, days,
                        installments, raw_text.
        """
        try:
            full_text = self._extract_text(pdf_bytes)
        except Exception as exc:
            return {
                "desc": None, "validity": None,
                "discount_percent": None, "days": [],
                "installments": None, "raw_text": f"PARSE ERROR: {exc}",
            }

        discount    = self._extract_discount(full_text)
        installments = self._extract_installments(full_text)
        validity    = self._extract_validity(full_text)
        days        = self._extract_days(full_text)
        cards       = self._extract_cards(full_text)

        desc = self._build_desc(
            discount=discount,
            installments=installments,
            validity=validity,
            days=days,
            cards=cards,
            fallback_text=full_text,
            commerce_name=commerce_name,
        )

        return {
            "desc":             desc,
            "validity":         validity,
            "discount_percent": discount,
            "days":             days,
            "installments":     installments,
            "raw_text":         full_text[:4000],  # first 4 k chars for debugging
        }

    # ── Text extraction ──────────────────────────────────────────
    def _extract_text(self, pdf_bytes: bytes) -> str:
        if not HAS_PDFPLUMBER:
            raise RuntimeError(
                "pdfplumber not installed — run: pip install pdfplumber"
            )
        pages: list[str] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=2, y_tolerance=4)
                if text:
                    pages.append(text.strip())
        return "\n".join(pages)

    # ── Field extractors ─────────────────────────────────────────
    def _extract_validity(self, text: str) -> str | None:
        # Try labelled line first
        m = _RE_VIGENCIA.search(text)
        if m:
            return m.group(1).strip()
        # Fallback: bare "del … al …" range anywhere in text
        m2 = _RE_DATE_RANGE.search(text)
        return m2.group(0).strip() if m2 else None

    def _extract_discount(self, text: str) -> int | None:
        matches = _RE_DESCUENTO.findall(text)
        if not matches:
            matches = _RE_PERCENT_BARE.findall(text)
        if not matches:
            return None
        try:
            values = [int(float(v.replace(",", "."))) for v in matches]
            # Return the most frequent value (avoids picking up a 0% or 100% edge case)
            return max(set(values), key=values.count)
        except (ValueError, TypeError):
            return None

    def _extract_installments(self, text: str) -> int | None:
        m = _RE_CUOTAS.search(text)
        if not m:
            return None
        n = int(m.group(1))
        full = m.group(0).lower()
        # Encode "sin interés" as 0 (convention used in the rest of the scraper)
        return 0 if ("sin inter" in full or "0%" in full or "tasa 0" in full) else n

    def _extract_days(self, text: str) -> list[str]:
        lower = text.lower()
        if re.search(r'todos\s+los\s+d[ií]as?', lower):
            return ["Todos"]
        found: list[str] = []
        for pattern, canonical in _DAY_NAMES_ES.items():
            if re.search(pattern, lower) and canonical not in found:
                found.append(canonical)
        # Preserve weekday order
        order = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        return sorted(found, key=lambda d: order.index(d) if d in order else 99)

    def _extract_cards(self, text: str) -> str | None:
        m = _RE_TARJETAS.search(text)
        return m.group(1).strip() if m else None

    # ── Description builder ──────────────────────────────────────
    def _build_desc(
        self,
        discount: int | None,
        installments: int | None,
        validity: str | None,
        days: list[str],
        cards: str | None,
        fallback_text: str,
        commerce_name: str,
    ) -> str | None:
        """
        Build a concise, display-ready description.

        Priority: structured fields → cleaned full text.
        """
        parts: list[str] = []

        # Benefit line
        if discount is not None:
            parts.append(f"{discount}% de descuento")
        if installments is not None:
            cuota_str = "sin interés" if installments == 0 else f"{installments} cuotas"
            parts.append(f"{installments if installments else ''} cuotas {cuota_str}".strip())

        # Conditions
        if cards:
            parts.append(f"Tarjetas: {cards}")
        if days:
            days_str = "Todos los días" if days == ["Todos"] else " / ".join(days)
            parts.append(f"Días: {days_str}")
        if validity:
            parts.append(f"Vigencia: {validity}")

        if parts:
            return "\n".join(parts)

        # Fallback: return the most informative lines from the raw text
        return self._clean_text(fallback_text, commerce_name) or None

    def _clean_text(self, text: str, commerce_name: str) -> str:
        """Strip boilerplate lines and return a compact version of the text."""
        skip_fragments = _BOILERPLATE_FRAGMENTS | {commerce_name.lower()}
        kept: list[str] = []
        for line in text.splitlines():
            s = line.strip()
            if not s or len(s) < 6:
                continue
            if any(frag in s.lower() for frag in skip_fragments):
                continue
            kept.append(s)
            if len(kept) >= 25:
                break
        return "\n".join(kept)


# ══════════════════════════════════════════════════════════════════
#  Content-hash cache
# ══════════════════════════════════════════════════════════════════

class PDFCache:
    """
    Persist parsed PDF results keyed by (URL, content MD5).

    On each scraper run the decision tree is:

    URL not in cache
        → download + parse → store → continue

    URL in cache AND MD5 of downloaded bytes matches stored hash
        → use cached result (no pdfplumber call, no regex, no disk write)

    URL in cache BUT MD5 differs (PDF changed on server)
        → re-parse → update cache entry → continue

    ``save()`` is a no-op if nothing changed, so it is safe to call
    unconditionally at the end of every scraper run.
    """

    def __init__(self, cache_path: Path = Path("reports/basa/pdf_cache.json")):
        self.path   = cache_path
        self._data: dict[str, dict] = self._load()
        self._dirty = False

    # ── Public API ──────────────────────────────────────────────────

    def needs_parse(self, url: str, pdf_bytes: bytes) -> bool:
        """Return True if this URL is new or its PDF content changed."""
        entry = self._data.get(url)
        if entry is None:
            return True
        return entry.get("hash") != self._md5(pdf_bytes)

    def get(self, url: str) -> dict | None:
        """Return the cached parsed dict, or None if not cached."""
        entry = self._data.get(url)
        return entry.get("parsed") if entry else None

    def store(self, url: str, pdf_bytes: bytes, parsed: dict) -> None:
        """Store a newly parsed result and mark the cache dirty."""
        self._data[url] = {
            "hash":       self._md5(pdf_bytes),
            "fetched_at": datetime.now().isoformat(),
            "parsed":     parsed,
        }
        self._dirty = True

    def save(self) -> None:
        """Flush to disk only if something changed since last load/save."""
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2))
        self._dirty = False

    def stats(self) -> dict:
        return {
            "total_entries": len(self._data),
            "cache_path":    str(self.path),
        }

    # ── Internal ────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                return {}
        return {}

    @staticmethod
    def _md5(data: bytes) -> str:
        return hashlib.md5(data).hexdigest()
