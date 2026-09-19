from __future__ import annotations

import re
from typing import Any, Dict

import communication_director


VERSION = "1.0-single-greeting"
_ORIGINAL_FRIENDLY_BODY = communication_director._friendly_body


def _strip_leading_greeting_blocks(text: str) -> str:
    """Remove short greeting-only paragraphs before Communication Director adds its canonical greeting."""
    chunks = re.split(r"\n\s*\n", (text or "").strip())
    greeting_re = re.compile(
        r"^\s*(?:hola\b|buen\s+d[ií]a\b|buenos\s+d[ií]as\b|buenas\s+tardes\b|buenas\s+noches\b)",
        re.IGNORECASE,
    )
    while chunks:
        block = chunks[0].strip()
        if not block or len(block) > 220 or not greeting_re.match(block):
            break
        chunks.pop(0)
    return "\n\n".join(chunks).strip()


def _single_greeting_friendly_body(kind: str, original: str, counterparty: str, ctx: Dict[str, Any]) -> str:
    cleaned = _strip_leading_greeting_blocks(original)
    return _ORIGINAL_FRIENDLY_BODY(kind, cleaned, counterparty, ctx)


if not getattr(communication_director, "_lumen_single_greeting_fix_installed", False):
    communication_director._friendly_body = _single_greeting_friendly_body
    communication_director._lumen_single_greeting_fix_installed = True

print({"communication_greeting_fix": {"version": VERSION, "status": "installed"}})
