from __future__ import annotations

"""Revenue Sprint 2.3: exact-document RFQ requirement extractor.

Broadens deterministic extraction of the three RFQ-minimum fields from already-linked current
official procurement text. It does not infer missing values and does not change search/send/spend or
binding authority.
"""

from typing import Any, Dict, Optional
import re

import revenue_sprint_v21_conversion_runtime as conversion

VERSION = "2.3-exact-document-requirement-extractor"
_ORIGINAL_EXTRACT_FIELD = conversion._extract_field


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_quantity(raw: str) -> Optional[str]:
    value = _clean(raw).replace(" ", "").replace(",", ".")
    if not re.fullmatch(r"\d{1,7}(?:\.\d{1,3})?", value):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if number <= 0 or number > 10_000_000:
        return None
    if number.is_integer():
        return str(int(number))
    return value


def _quantity_from_document(text: str) -> Optional[str]:
    patterns = (
        r"\b(?:cantidad|cant(?:idad)?\.?|cant\.)\s*(?:total\s*)?(?:[:=\-]|de)?\s*(\d{1,7}(?:[.,]\d{1,3})?)\b",
        r"\b(?:unidades?|unidad|uds?\.?|u\.|un\.)\s*[xX]\s*(\d{1,7}(?:[.,]\d{1,3})?)\b",
        r"\bx\s*(\d{1,7}(?:[.,]\d{1,3})?)\s*(?:unidades?|uds?\.?|u\.|un\.)?\b",
        r"\b(\d{1,7}(?:[.,]\d{1,3})?)\s*(?:unidades?|uds?\.?|u\.|un\.)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        value = _normalize_quantity(match.group(1))
        if value:
            return value
    return None


def _delivery_from_document(text: str) -> Optional[str]:
    patterns = (
        r"(?:lugar|sitio|domicilio|punto)\s+de\s+(?:entrega|recepci[oó]n|provisi[oó]n|suministro)\s*[:\-]\s*([^;\n]{3,180})",
        r"(?:destino|direcci[oó]n\s+de\s+entrega)\s*[:\-]\s*([^;\n]{3,180})",
        r"(?:entregar|entrega(?:rse)?|ser[aá]n?\s+entregad[oa]s?)\s+(?:en|a)\s+([^;\n]{3,180})",
        r"entrega\s+(?:en|a\s+realizarse\s+en)\s+([^;\n]{3,180})",
    )
    stop = re.compile(
        r"\s+(?:plazo|forma\s+de\s+pago|condiciones?|garant[ií]a|rengl[oó]n|item|ítem|cantidad|especificaci[oó]n)\b",
        flags=re.I,
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        value = _clean(match.group(1))
        value = stop.split(value, maxsplit=1)[0].strip(" .,:;-")[:160]
        if len(value) >= 3 and not re.fullmatch(r"\d+(?:[.,]\d+)?", value):
            return value
    return None


def _technical_scope_from_document(signal: Dict[str, Any], text: str) -> Optional[str]:
    lower = text.lower()
    if not any(term in lower for term in ("licit", "adquis", "solicitud de cot", "compra", "contrat", "rengl", "ítem", "item")):
        return None
    patterns = (
        r"objeto\s+de\s+la\s+contrataci[oó]n\s*[:\-]\s*([^;\n]{12,420})",
        r"objeto\s+de\s+la\s+compra\s*[:\-]\s*([^;\n]{12,420})",
        r"objeto\s*[:\-]\s*([^;\n]{12,420})",
        r"(?:descripci[oó]n|detalle)\s+(?:del\s+)?(?:rengl[oó]n|[ií]tem|item)\s*[:\-]\s*([^;\n]{12,420})",
        r"(?:rengl[oó]n|[ií]tem|item)\s*(?:n[°ºo]\.?\s*)?\d+\s*[:\-]\s*([^;\n]{12,420})",
    )
    stop = re.compile(
        r"\s+(?:cantidad|cant\.|lugar\s+de\s+entrega|plazo|forma\s+de\s+pago|garant[ií]a|presupuesto)\b",
        flags=re.I,
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        value = _clean(match.group(1))
        value = stop.split(value, maxsplit=1)[0].strip(" .,:;-")[:420]
        if len(value) >= 12:
            return value
    return None


def _extract_field_v23(field: str, signal: Dict[str, Any], text: str) -> Optional[str]:
    clean_text = _clean(text)
    if field == "technical_scope":
        precise = _technical_scope_from_document(signal, clean_text)
        if precise:
            return precise
        return _ORIGINAL_EXTRACT_FIELD(field, signal, clean_text)
    if field == "quantity":
        original = _ORIGINAL_EXTRACT_FIELD(field, signal, clean_text)
        if original:
            return original
        return _quantity_from_document(clean_text)
    if field == "delivery_location":
        original = _ORIGINAL_EXTRACT_FIELD(field, signal, clean_text)
        if original:
            return original
        return _delivery_from_document(clean_text)
    return _ORIGINAL_EXTRACT_FIELD(field, signal, clean_text)


conversion._extract_field = _extract_field_v23

print(
    {
        "revenue_sprint_v23_requirement_extractor": {
            "version": VERSION,
            "status": "installed",
            "fields": ["technical_scope", "quantity", "delivery_location"],
            "exact_text_only": True,
            "inference_allowed": False,
            "search_spend_increased": False,
            "outbound_caps_increased": False,
            "binding_authority_changed": False,
        }
    },
    flush=True,
)
