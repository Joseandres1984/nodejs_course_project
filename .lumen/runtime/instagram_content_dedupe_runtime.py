from __future__ import annotations

"""Shared Instagram anti-duplication guard for LUMEN.

The guard is deliberately fail-closed at publication time. It detects exact and
near-duplicate visible headlines and captions against verified published jobs,
and it can also rotate editorial/thematic headlines before an asset is rendered.
It never creates publication authority, changes monetary authority or publishes
content by itself.
"""

import re
import sys
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Sequence, Tuple

VERSION = "1.0-instagram-content-dedupe"
HISTORY_LIMIT = 30
HEADLINE_SIMILARITY_LIMIT = 0.82
CAPTION_SIMILARITY_LIMIT = 0.93

EXTRA_HEADLINES: Dict[str, List[str]] = {
    "buyer_value": [
        "Comparar mejor también es comprar mejor en B2B.",
        "Una necesidad concreta merece proveedores realmente comparables.",
        "Antes de elegir proveedor, ordená la evidencia.",
        "Comprar B2B con criterio empieza por reducir el ruido.",
        "Más contexto para elegir entre alternativas B2B.",
    ],
    "authority": [
        "La información vale más cuando ayuda a decidir.",
        "Señales dispersas no son inteligencia comercial.",
        "Evidencia primero. Decisiones comerciales después.",
        "Convertir datos en criterio también es una ventaja B2B.",
        "Una oportunidad comercial necesita contexto para ser útil.",
    ],
    "supplier_value": [
        "La mejor prospección empieza por encontrar dónde encaja tu oferta.",
        "No se trata de contactar más: se trata de encajar mejor.",
        "Tu oferta B2B necesita demanda compatible, no más ruido.",
        "Proveedores y demanda: el valor aparece cuando hay encaje.",
        "Una buena oferta gana fuerza cuando encuentra la necesidad correcta.",
    ],
    "education": [
        "Tres filtros simples para comparar una compra B2B con criterio.",
        "Antes de decidir una compra B2B, compará algo más que precio.",
        "Una cotización no alcanza para comparar proveedores.",
        "Precio, especificación y entrega: compará el conjunto.",
        "Comprar mejor exige comparar ofertas realmente equivalentes.",
    ],
    "partner_growth": [
        "Un catálogo también puede ser el inicio de una oportunidad B2B.",
        "Encontrar demanda compatible puede abrir otro canal para tu catálogo.",
        "Tu tienda puede llegar a oportunidades fuera de su tráfico habitual.",
        "Catálogo y demanda: el desafío es encontrar el encaje correcto.",
        "Más contexto puede convertir un catálogo en una conversación B2B.",
    ],
    "travel": [
        "El turismo también es una red de oportunidades entre empresas.",
        "Viajes: detrás de cada reserva existe un ecosistema B2B.",
        "Agencias, alojamientos y servicios: también hay oportunidades por conectar.",
        "El negocio de viajes va mucho más allá de vender reservas.",
        "Turismo B2B: oferta y demanda también necesitan encontrarse.",
    ],
    "technology": [
        "Tecnología B2B: la oportunidad aparece cuando oferta y demanda encajan.",
        "Integración, servicio y producto también generan señales comerciales.",
        "La tecnología abre negocios cuando resuelve una necesidad concreta.",
        "En tecnología, detectar demanda importa tanto como tener producto.",
        "Tecnología B2B: menos ruido y más encaje comercial.",
    ],
    "construction": [
        "Cada obra activa una red de proveedores y necesidades.",
        "Construcción B2B: materiales, servicios y demanda por conectar.",
        "Una obra también es una cadena de oportunidades comerciales.",
        "Abastecimiento y construcción: encontrar el proveedor correcto importa.",
        "Construcción: detrás de cada necesidad aparece un mercado de alternativas.",
    ],
    "industry": [
        "Industria B2B: cada requerimiento abre alternativas de mercado.",
        "Una necesidad industrial puede activar una nueva búsqueda de proveedores.",
        "Equipos, repuestos y servicios: la industria también es un mapa de oportunidades.",
        "Comprar para industria empieza por entender bien la necesidad.",
        "Industria: más evidencia para encontrar mejores alternativas B2B.",
    ],
    "import_export": [
        "Comercio exterior: primero mercado y evidencia, después operación.",
        "Importar o exportar también empieza por detectar el encaje correcto.",
        "Nuevos mercados requieren señales, contexto y contrapartes compatibles.",
        "Comercio exterior: conectar oferta y demanda antes de mover mercadería.",
        "Exportar mejor empieza por entender dónde existe demanda.",
    ],
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def normalize_visible(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _text(value).casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"#[\w-]+", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def text_similarity(left: Any, right: Any) -> float:
    a = normalize_visible(left)
    b = normalize_visible(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    seq = SequenceMatcher(None, a, b).ratio()
    ta, tb = set(a.split()), set(b.split())
    union = ta | tb
    jaccard = len(ta & tb) / len(union) if union else 0.0
    return max(seq, jaccard)


def _receipt_ids(state: Dict[str, Any]) -> set[str]:
    return {
        _text(row.get("distribution_job_id"))
        for row in state.get("distribution_receipts", []) or []
        if isinstance(row, dict)
        and _text(row.get("distribution_job_id"))
        and (row.get("external_post_id") or row.get("external_url"))
    }


def published_instagram_jobs(state: Dict[str, Any], limit: int = HISTORY_LIMIT) -> List[Dict[str, Any]]:
    receipt_ids = _receipt_ids(state)
    rows: List[Dict[str, Any]] = []
    for job in reversed(state.get("distribution_operator_jobs", []) or []):
        if not isinstance(job, dict) or _text(job.get("channel")).lower() != "instagram":
            continue
        jid = _text(job.get("id"))
        if jid in receipt_ids or _text(job.get("status")).lower() in {"published", "verified_published"}:
            rows.append(job)
            if len(rows) >= max(1, limit):
                break
    return rows


def recent_headlines(state: Dict[str, Any], limit: int = HISTORY_LIMIT, *, exclude_job_id: str = "") -> List[str]:
    values: List[str] = []
    seen: set[str] = set()
    for row in reversed(state.get("instagram_editorial_history", []) or []):
        if not isinstance(row, dict) or _text(row.get("job_id")) == exclude_job_id:
            continue
        headline = _text(row.get("headline"))
        key = normalize_visible(headline)
        if headline and key and key not in seen:
            seen.add(key)
            values.append(headline)
            if len(values) >= limit:
                break
    for job in published_instagram_jobs(state, limit=limit):
        if _text(job.get("id")) == exclude_job_id:
            continue
        headline = _text(job.get("headline"))
        key = normalize_visible(headline)
        if headline and key and key not in seen:
            seen.add(key)
            values.append(headline)
            if len(values) >= limit:
                break
    return values[:limit]


def choose_diverse_headline(
    state: Dict[str, Any],
    options: Sequence[str],
    *,
    key: str = "",
    exclude_job_id: str = "",
) -> Tuple[str, float]:
    candidates = [_text(x) for x in options if _text(x)]
    if not candidates:
        return "Inteligencia comercial B2B con más criterio.", 0.0
    recent = recent_headlines(state, exclude_job_id=exclude_job_id)
    if not recent:
        return candidates[0], 0.0

    ranked: List[Tuple[float, int, str]] = []
    for idx, candidate in enumerate(candidates):
        max_similarity = max((text_similarity(candidate, old) for old in recent), default=0.0)
        ranked.append((max_similarity, idx, candidate))
    ranked.sort(key=lambda row: (row[0], row[1]))
    score, _, title = ranked[0]
    return title, float(round(score, 4))


def duplicate_reasons(state: Dict[str, Any], job: Dict[str, Any], limit: int = HISTORY_LIMIT) -> List[str]:
    reasons: List[str] = []
    jid = _text(job.get("id"))
    headline = _text(job.get("headline"))
    caption = _text(job.get("caption") or job.get("copy"))
    for previous in published_instagram_jobs(state, limit=limit):
        if _text(previous.get("id")) == jid:
            continue
        old_headline = _text(previous.get("headline"))
        old_caption = _text(previous.get("caption") or previous.get("copy"))
        hs = text_similarity(headline, old_headline) if headline and old_headline else 0.0
        cs = text_similarity(caption, old_caption) if caption and old_caption else 0.0
        if hs >= 0.999:
            reasons.append("duplicate_headline_exact")
        elif hs >= HEADLINE_SIMILARITY_LIMIT:
            reasons.append("duplicate_headline_near")
        if cs >= 0.999:
            reasons.append("duplicate_caption_exact")
        elif cs >= CAPTION_SIMILARITY_LIMIT:
            reasons.append("duplicate_caption_near")
        if reasons:
            break
    return sorted(set(reasons))


def remote_caption_duplicate_reasons(candidate_caption: Any, remote_rows: Iterable[Dict[str, Any]]) -> List[str]:
    caption = _text(candidate_caption)
    if not caption:
        return []
    for row in remote_rows or []:
        if not isinstance(row, dict):
            continue
        old = _text(row.get("caption"))
        if not old:
            continue
        similarity = text_similarity(caption, old)
        if similarity >= 0.999:
            return ["remote_duplicate_caption_exact"]
        if similarity >= CAPTION_SIMILARITY_LIMIT:
            return ["remote_duplicate_caption_near"]
    return []


def patch_publish_control(module: Any) -> None:
    if getattr(module, "_INSTAGRAM_CONTENT_DEDUPE_V1", False):
        return
    if not hasattr(module, "attempt_publish_approved") or not hasattr(module, "_job_by_id"):
        return
    original_attempt = module.attempt_publish_approved

    def attempt_with_dedupe(state: Dict[str, Any], job_id: str) -> Dict[str, Any]:
        job = module._job_by_id(state, job_id)
        if job and _text(job.get("channel")).lower() == "instagram":
            reasons = duplicate_reasons(state, job)
            if reasons:
                approvals = module._approval_store(state)
                approval = approvals.get(str(job_id)) or {"job_id": str(job_id)}
                approval["status"] = "DUPLICATE_BLOCKED"
                approval["duplicate_reasons"] = reasons
                approval["dedupe_policy_version"] = VERSION
                approval["blocked_at"] = module.utcnow() if hasattr(module, "utcnow") else None
                approvals[str(job_id)] = approval
                job["status"] = "blocked_duplicate_content"
                job["duplicate_reasons"] = reasons
                job["dedupe_policy_version"] = VERSION
                if hasattr(module, "_append_audit"):
                    module._append_audit(state, {
                        "status": "DUPLICATE_BLOCKED",
                        "job_id": str(job_id),
                        "reasons": reasons,
                        "policy_version": VERSION,
                    })
                return {
                    "ok": False,
                    "status": "DUPLICATE_BLOCKED",
                    "reasons": reasons,
                    "policy_version": VERSION,
                    "published": False,
                }
        return dict(original_attempt(state, job_id) or {})

    module.attempt_publish_approved = attempt_with_dedupe
    module._INSTAGRAM_CONTENT_DEDUPE_V1 = True


def patch_editorial_module(module: Any) -> None:
    if getattr(module, "_INSTAGRAM_TITLE_DIVERSITY_V1", False):
        return
    if not hasattr(module, "_choose_headline"):
        return
    original = module._choose_headline

    def choose_with_diversity(state: Dict[str, Any], slot: str, brief: Dict[str, Any], strategy: str) -> str:
        pillar = _text(brief.get("pillar"))
        options = list(brief.get("headlines") or []) + EXTRA_HEADLINES.get(pillar, [])
        if not options:
            return original(state, slot, brief, strategy)
        title, similarity = choose_diverse_headline(state, options, key=f"{slot}|{strategy}|{pillar}")
        state["instagram_title_dedupe_last_selection"] = {
            "version": VERSION,
            "slot": slot,
            "pillar": pillar,
            "headline": title,
            "max_similarity_to_recent": similarity,
        }
        return title

    module._choose_headline = choose_with_diversity
    module._INSTAGRAM_TITLE_DIVERSITY_V1 = True


def patch_thematic_module(module: Any) -> None:
    if getattr(module, "_INSTAGRAM_THEMATIC_TITLE_DIVERSITY_V1", False):
        return
    if not hasattr(module, "prepare_job"):
        return
    original = module.prepare_job

    def prepare_with_diversity(state: Dict[str, Any], theme: str, request_id: str, goal: str = "", notes: str = "") -> Dict[str, Any]:
        result = dict(original(state, theme, request_id, goal, notes) or {})
        if result.get("status") != "prepared":
            return result
        jid = _text(result.get("job_id"))
        job = next((x for x in state.get("distribution_operator_jobs", []) or [] if isinstance(x, dict) and _text(x.get("id")) == jid), None)
        if not job:
            return result
        theme_key = _text(job.get("theme") or theme)
        options = [_text(job.get("headline"))] + EXTRA_HEADLINES.get(theme_key, [])
        title, similarity = choose_diverse_headline(state, options, key=f"{request_id}|{theme_key}", exclude_job_id=jid)
        if title and title != _text(job.get("headline")):
            job["headline"] = title
            job["updated_at"] = module._now() if hasattr(module, "_now") else job.get("updated_at")
        job["title_dedupe_version"] = VERSION
        job["title_similarity_to_recent"] = similarity
        history = state.get("instagram_editorial_history", []) or []
        for row in reversed(history):
            if isinstance(row, dict) and _text(row.get("job_id")) == jid:
                row["headline"] = job.get("headline")
                row["title_dedupe_version"] = VERSION
                row["title_similarity_to_recent"] = similarity
                break
        result["headline"] = job.get("headline")
        result["title_dedupe_version"] = VERSION
        result["title_similarity_to_recent"] = similarity
        return result

    module.prepare_job = prepare_with_diversity
    module._INSTAGRAM_THEMATIC_TITLE_DIVERSITY_V1 = True


def install_loaded() -> None:
    publish = sys.modules.get("instagram_publish_control")
    if publish is not None:
        patch_publish_control(publish)
    editorial = sys.modules.get("instagram_pro_editorial_runtime")
    if editorial is not None:
        patch_editorial_module(editorial)
    thematic = sys.modules.get("zero_instagram_thematic_prepare_v2")
    if thematic is not None:
        patch_thematic_module(thematic)


def install() -> None:
    install_loaded()
