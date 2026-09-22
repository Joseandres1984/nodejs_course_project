from __future__ import annotations

"""Paid x402 fulfillment lane for LUMEN Zero.

This module is intentionally narrow: it converts already-settled, already-queued human
microproduct orders into evidence-backed report JSON. It never creates charges, never spends,
never treats payment authorization as revenue, and never sends a client deliverable itself.

A later fail-closed PDF/delivery gate consumes only ``report_ready`` jobs.
"""

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

import d1_persistence_runtime as d1
import scout_connector

VERSION = "1.0-paid-fulfillment-research"
MAX_QUERIES_PER_JOB = max(1, min(5, int(os.getenv("LUMEN_PAID_FULFILLMENT_MAX_QUERIES", "3"))))
MAX_RESULTS_PER_QUERY = max(3, min(10, int(os.getenv("LUMEN_PAID_FULFILLMENT_RESULTS_PER_QUERY", "6"))))
MIN_EVIDENCE = max(2, min(5, int(os.getenv("LUMEN_PAID_FULFILLMENT_MIN_EVIDENCE", "2"))))
MAX_ATTEMPTS = max(1, min(6, int(os.getenv("LUMEN_PAID_FULFILLMENT_MAX_ATTEMPTS", "3"))))
RECLAIM_MINUTES = max(15, min(180, int(os.getenv("LUMEN_PAID_FULFILLMENT_RECLAIM_MINUTES", "45"))))

PRODUCTS: Dict[str, Dict[str, str]] = {
    "MP-SUPPLIER-SNAPSHOT": {"slug": "supplier-snapshot", "title": "Supplier Snapshot", "service_id": "SRV-SUPPLIERCHECK"},
    "MP-QUOTE-SANITY": {"slug": "quote-sanity", "title": "Quote Sanity Check", "service_id": "SRV-QUOTECHECK"},
    "MP-TENDER-SCAN": {"slug": "tender-scan", "title": "Tender Quick Scan", "service_id": "SRV-TENDER-HUNTER"},
    "MP-SOURCING-5": {"slug": "sourcing-5", "title": "Supplier Shortlist 5", "service_id": "SRV-SOURCING-EXPRESS"},
    "MP-BUYER-SIGNALS": {"slug": "buyer-signals", "title": "Buyer Signal Scan", "service_id": "SRV-B2B-PROSPECTING"},
    "MP-EXPORT-PULSE": {"slug": "export-pulse", "title": "Export Market Pulse", "service_id": "SRV-EXPORT-SCOUT"},
}

LOW_VALUE_HOSTS = {
    "facebook.com", "www.facebook.com", "instagram.com", "www.instagram.com",
    "pinterest.com", "www.pinterest.com", "tiktok.com", "www.tiktok.com",
}
RESERVED_HOSTS = {"example.com", "example.org", "example.net", "example.invalid", "localhost"}
STOPWORDS = {
    "para", "como", "este", "esta", "esto", "desde", "hasta", "sobre", "entre", "antes", "despues",
    "quiero", "necesito", "buscar", "revisar", "analizar", "proveedor", "proveedores", "empresa", "empresas",
    "the", "and", "with", "from", "that", "this", "need", "please", "find", "check", "supplier", "suppliers",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(result: Any, index: int = 0) -> List[Dict[str, Any]]:
    statements = d1._result_statements(result)
    if len(statements) <= index:
        return []
    return d1._statement_rows(statements[index])


def _text(value: Any, limit: int = 8000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _json(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _clean_evidence(items: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        url = _text(item.get("url"), 1000)
        title = _text(item.get("title"), 300)
        snippet = _text(item.get("snippet"), 1000)
        host = _host(url)
        if not url.startswith(("https://", "http://")) or not host:
            continue
        if host in RESERVED_HOSTS or host in LOW_VALUE_HOSTS:
            continue
        key = url.split("#", 1)[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "title": title or host,
            "url": url,
            "note": snippet or f"Fuente pública localizada en {host}.",
            "observed_at": _now()[:10],
            "host": host,
        })
    return out


def _keywords(requirement: str, limit: int = 8) -> List[str]:
    words = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9][A-Za-zÁÉÍÓÚáéíóúÑñ0-9._/-]{2,}", requirement)
    ranked: List[str] = []
    seen: set[str] = set()
    for word in words:
        norm = word.lower().strip(".,;:()[]{}")
        if len(norm) < 4 or norm in STOPWORDS or norm in seen:
            continue
        seen.add(norm)
        ranked.append(word.strip(".,;:()[]{}"))
        if len(ranked) >= limit:
            break
    return ranked


def _base_phrase(requirement: str) -> str:
    keys = _keywords(requirement, 7)
    return " ".join(keys) if keys else requirement[:220]


def _queries(item_id: str, requirement: str) -> List[str]:
    phrase = _base_phrase(requirement)
    mapping = {
        "MP-SUPPLIER-SNAPSHOT": [
            f'"{phrase}" proveedor empresa sitio oficial',
            f'"{phrase}" catálogo contacto',
            f'"{phrase}" company supplier official',
        ],
        "MP-QUOTE-SANITY": [
            f'"{phrase}" precio proveedor',
            f'"{phrase}" price distributor',
            f'"{phrase}" catálogo precio',
        ],
        "MP-TENDER-SCAN": [
            f'"{phrase}" licitación OR contratación OR concurso',
            f'"{phrase}" procurement OR tender OR bid',
            f'"{phrase}" compras públicas',
        ],
        "MP-SOURCING-5": [
            f'"{phrase}" fabricante proveedor distribuidor',
            f'"{phrase}" manufacturer supplier distributor',
            f'"{phrase}" venta industrial contacto',
        ],
        "MP-BUYER-SIGNALS": [
            f'"{phrase}" compras abastecimiento importador',
            f'"{phrase}" buyer procurement importer',
            f'"{phrase}" requiere OR busca OR compra',
        ],
        "MP-EXPORT-PULSE": [
            f'"{phrase}" import market demand',
            f'"{phrase}" importer distributor market',
            f'"{phrase}" comercio exterior demanda mercado',
        ],
    }
    return mapping.get(item_id, [phrase])[:MAX_QUERIES_PER_JOB]


def _search(query: str) -> List[Dict[str, Any]]:
    try:
        return list(scout_connector.search(query) or [])[:MAX_RESULTS_PER_QUERY]
    except Exception as exc:
        print({"paid_fulfillment_search": {"status": "degraded", "query": query[:180], "error": f"{type(exc).__name__}: {str(exc)[:240]}"}}, flush=True)
        return []


def _report_id(item_id: str, order_id: str) -> str:
    code = item_id.removeprefix("MP-").replace("_", "-")[:18]
    tail = re.sub(r"[^A-Za-z0-9]", "", order_id)[-10:].upper()
    return f"LUMEN-{code}-{tail}"


def _confidence(evidence_count: int) -> str:
    if evidence_count >= 7:
        return "alta"
    if evidence_count >= 4:
        return "media"
    return "baja"


def _table_for(item_id: str, evidence: List[Dict[str, str]]) -> Dict[str, Any]:
    limit = {
        "MP-SUPPLIER-SNAPSHOT": 5,
        "MP-QUOTE-SANITY": 6,
        "MP-TENDER-SCAN": 5,
        "MP-SOURCING-5": 5,
        "MP-BUYER-SIGNALS": 10,
        "MP-EXPORT-PULSE": 6,
    }.get(item_id, 5)
    rows = [[e["title"][:100], e["host"], e["note"][:220], e["url"]] for e in evidence[:limit]]
    titles = {
        "MP-SUPPLIER-SNAPSHOT": "Señales públicas del proveedor",
        "MP-QUOTE-SANITY": "Referencias públicas para contraste",
        "MP-TENDER-SCAN": "Oportunidades y señales localizadas",
        "MP-SOURCING-5": "Shortlist pública inicial",
        "MP-BUYER-SIGNALS": "Señales de compradores potenciales",
        "MP-EXPORT-PULSE": "Señales por mercado/fuente",
    }
    return {"title": titles.get(item_id, "Evidencia pública"), "columns": ["Resultado", "Fuente", "Señal", "URL"], "rows": rows}


def _findings(item_id: str, evidence: List[Dict[str, str]]) -> List[Dict[str, str]]:
    count = len(evidence)
    hosts = len({e["host"] for e in evidence})
    base = [
        {"title": "Evidencia pública localizada", "detail": f"Se localizaron {count} referencias públicas utilizables en {hosts} dominios distintos. La selección se limita a lo visible y verificable en las fuentes citadas.", "confidence": _confidence(count)},
        {"title": "Trazabilidad preservada", "detail": "Cada señal incluida conserva su URL para que el cliente pueda revisar el origen. LUMEN no convierte ausencia de evidencia en una afirmación positiva.", "confidence": "alta"},
    ]
    specifics = {
        "MP-SUPPLIER-SNAPSHOT": ("Alcance del snapshot", "La revisión sirve como filtro inicial de identidad/presencia pública; no certifica solvencia, stock, capacidad productiva ni cumplimiento futuro."),
        "MP-QUOTE-SANITY": ("Contraste orientativo", "Las referencias públicas permiten contextualizar la cotización, pero una equivalencia de precio sólo es válida cuando especificación, cantidad, moneda, impuestos, plazo y condición comercial son comparables."),
        "MP-TENDER-SCAN": ("Oportunidades sujetas a bases", "Las señales localizadas deben validarse contra pliegos, fechas, elegibilidad y sitio oficial antes de tomar una decisión de participación."),
        "MP-SOURCING-5": ("Shortlist no equivale a homologación", "Los candidatos son puntos de partida para contacto. Disponibilidad, precio, certificaciones y encaje técnico final requieren confirmación directa."),
        "MP-BUYER-SIGNALS": ("Señal no equivale a intención confirmada", "Una señal pública ayuda a priorizar cuentas, pero no demuestra que la empresa vaya a comprar ni autoriza contacto invasivo."),
        "MP-EXPORT-PULSE": ("Pulso de mercado", "Las señales públicas sirven para orientar dónde profundizar; no sustituyen estadísticas oficiales completas, asesoría aduanera ni validación de un importador específico."),
    }
    title, detail = specifics.get(item_id, ("Alcance", "La investigación se limita a evidencia pública verificable."))
    base.append({"title": title, "detail": detail, "confidence": "alta"})
    return base


def _next_steps(item_id: str) -> List[str]:
    return {
        "MP-SUPPLIER-SNAPSHOT": ["Confirmar directamente identidad legal, alcance, stock/plazo y documentación aplicable antes de comprar.", "Solicitar una oferta formal y referencias cuando el riesgo de compra lo justifique."],
        "MP-QUOTE-SANITY": ["Normalizar especificación, cantidad, moneda, impuestos, Incoterm/plazo y vigencia antes de comparar precios.", "Pedir una segunda referencia comparable si la decisión económica es material."],
        "MP-TENDER-SCAN": ["Abrir la fuente oficial de cada oportunidad y validar fecha límite, pliego, requisitos y elegibilidad.", "Descartar cualquier señal que no pueda confirmarse en una fuente oficial o institucional."],
        "MP-SOURCING-5": ["Contactar candidatos con una misma especificación para obtener respuestas comparables.", "Validar ficha técnica, certificaciones, stock/plazo, entrega, vigencia y condiciones antes de adjudicar."],
        "MP-BUYER-SIGNALS": ["Priorizar las cuentas con señales más recientes y específicas.", "Verificar empresa y contacto corporativo antes de cualquier outreach, respetando opt-outs y normativa aplicable."],
        "MP-EXPORT-PULSE": ["Elegir el mercado con mejor evidencia y profundizar requisitos de acceso, logística y compradores.", "Confirmar datos regulatorios/aduaneros con fuentes oficiales antes de operar."],
    }.get(item_id, ["Validar la evidencia antes de tomar una decisión."])


def _recommendation(item_id: str, evidence: List[Dict[str, str]]) -> str:
    if len(evidence) < MIN_EVIDENCE:
        return "No emitir una decisión todavía: la evidencia pública disponible es insuficiente para un entregable confiable."
    return {
        "MP-SUPPLIER-SNAPSHOT": "Usar el snapshot como filtro inicial y avanzar sólo después de una validación comercial/documental directa del proveedor.",
        "MP-QUOTE-SANITY": "Usar las referencias como contexto y decidir sólo con comparables técnicamente equivalentes y condiciones comerciales normalizadas.",
        "MP-TENDER-SCAN": "Priorizar únicamente oportunidades que puedan confirmarse en su fuente oficial y cuyo pliego encaje con la capacidad real del cliente.",
        "MP-SOURCING-5": "Contactar primero a los candidatos con señales públicas más específicas y mantener alternativas hasta obtener evidencia técnica y comercial comparable.",
        "MP-BUYER-SIGNALS": "Priorizar las señales más concretas y recientes, y verificar cada cuenta/contacto antes de iniciar outreach.",
        "MP-EXPORT-PULSE": "Profundizar el mercado con mayor densidad y calidad de señales antes de comprometer recursos comerciales o logísticos.",
    }.get(item_id, "Avanzar sólo con evidencia verificable y validación directa cuando corresponda.")


def _build_report(job: Dict[str, Any], evidence: List[Dict[str, str]], queries: List[str]) -> Dict[str, Any]:
    item_id = _text(job.get("item_id"), 100)
    product = PRODUCTS[item_id]
    requirement = _text(job.get("requirement"), 8000)
    company = _text(job.get("company"), 180) or "Cliente LUMEN"
    count = len(evidence)
    title = product["title"]
    summary = f"LUMEN investigó el requerimiento recibido y reunió {count} referencias públicas utilizables. El resultado es un análisis acotado del producto {title}, con fuentes visibles, límites explícitos y próximos pasos; no se presentan como hechos elementos que las fuentes no demuestran."
    return {
        "template_key": product["slug"],
        "product_or_service_id": product["slug"],
        "report_id": _report_id(item_id, _text(job.get("order_id"), 100)),
        "client": company,
        "generated_at": _now(),
        "evidence_cutoff": _now(),
        "client_request": requirement,
        "answer": summary,
        "executive_summary": summary,
        "confidence": _confidence(count),
        "metrics": {
            "fuentes_utilizables": str(count),
            "dominios_distintos": str(len({e["host"] for e in evidence})),
            "consultas_publicas": str(len(queries)),
        },
        "findings": _findings(item_id, evidence),
        "tables": [_table_for(item_id, evidence)],
        "risks": [
            {"level": "medio", "title": "Evidencia pública limitada", "detail": "La disponibilidad pública de información puede ser incompleta, desactualizada o no demostrar condiciones comerciales actuales."},
            {"level": "bajo", "title": "Inferencias controladas", "detail": "LUMEN separa señales observadas de afirmaciones que requieren confirmación directa u oficial."},
        ],
        "evidence": [{k: e[k] for k in ("title", "url", "note", "observed_at")} for e in evidence],
        "methodology": ["Búsqueda pública acotada y deduplicada", "Selección de fuentes con URL trazable", "Separación entre evidencia observada e inferencias", "Revisión de límites del microproducto"],
        "limitations": ["No es auditoría, certificación legal/financiera ni inspección física.", "Precio, stock, capacidad, elegibilidad o intención de compra sólo se consideran confirmados cuando la evidencia específica lo demuestra."],
        "next_steps": _next_steps(item_id),
        "recommendation": _recommendation(item_id, evidence),
        "fulfillment": {
            "order_id": _text(job.get("order_id"), 100),
            "receipt_id": _text(job.get("receipt_id"), 100),
            "brief_id": _text(job.get("brief_id"), 100),
            "research_version": VERSION,
            "queries": queries,
            "zero_cost_research": True,
            "outgoing_spend": False,
        },
    }


def _ensure_schema() -> None:
    d1._request({"batch": [
        {"sql": "CREATE TABLE IF NOT EXISTS lumen_paid_fulfillment_jobs (order_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, status TEXT NOT NULL, receipt_id TEXT NOT NULL, brief_id TEXT NOT NULL, item_id TEXT NOT NULL, service_id TEXT NOT NULL, amount_usd REAL NOT NULL, delivery_email TEXT NOT NULL, company TEXT, requirement TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, claimed_at TEXT, report_json TEXT, evidence_count INTEGER NOT NULL DEFAULT 0, last_error TEXT)", "params": []},
        {"sql": "CREATE INDEX IF NOT EXISTS idx_lumen_paid_fulfillment_status ON lumen_paid_fulfillment_jobs(status,updated_at)", "params": []},
    ]})


def _sync_paid_orders() -> int:
    now = _now()
    sql = """
    INSERT OR IGNORE INTO lumen_paid_fulfillment_jobs(
      order_id,created_at,updated_at,status,receipt_id,brief_id,item_id,service_id,amount_usd,delivery_email,company,requirement,attempts
    )
    SELECT o.id, ?, ?, 'queued', r.id, b.id, o.item_id, o.service_id, o.amount_usd, b.email, COALESCE(b.company,''), b.details, 0
    FROM lumen_machine_orders o
    JOIN lumen_x402_receipts r ON r.id=json_extract(o.remote_metadata,'$.x402_receipt_id')
    JOIN lumen_conversion_leads b ON b.id=json_extract(o.remote_metadata,'$.brief_id')
    WHERE o.status='x402_paid_queued'
      AND o.item_type='product'
      AND r.status='redeemed_queued'
      AND json_extract(r.request_metadata,'$.settlement.success')=1
      AND json_extract(o.remote_metadata,'$.payment_verified')='true'
      AND json_extract(o.remote_metadata,'$.payment_settled')='true'
      AND b.status='paid_queued'
      AND b.technical_canary=0
      AND LENGTH(TRIM(COALESCE(b.details,'')))>=8
      AND o.item_id IN ('MP-SUPPLIER-SNAPSHOT','MP-QUOTE-SANITY','MP-TENDER-SCAN','MP-SOURCING-5','MP-BUYER-SIGNALS','MP-EXPORT-PULSE')
    """
    result = d1._request({"sql": sql, "params": [now, now]})
    statements = d1._result_statements(result)
    meta = statements[0].get("meta", {}) if statements and isinstance(statements[0], dict) else {}
    try:
        return int(meta.get("changes") or meta.get("rows_written") or 0)
    except Exception:
        return 0


def _reclaim_stale() -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=RECLAIM_MINUTES)).isoformat()
    d1._request({"sql": "UPDATE lumen_paid_fulfillment_jobs SET status='queued', claimed_at=NULL, updated_at=?, last_error='stale_claim_reclaimed' WHERE status='researching' AND claimed_at IS NOT NULL AND claimed_at < ? AND attempts < ?", "params": [_now(), cutoff, MAX_ATTEMPTS]})


def _claim_one() -> Dict[str, Any] | None:
    token = f"CLAIM-{uuid.uuid4().hex[:16].upper()}"
    now = _now()
    sql = """
    UPDATE lumen_paid_fulfillment_jobs
    SET status='researching', claimed_at=?, updated_at=?, attempts=attempts+1, last_error=NULL
    WHERE order_id=(
      SELECT order_id FROM lumen_paid_fulfillment_jobs
      WHERE status='queued' AND attempts < ?
      ORDER BY created_at ASC LIMIT 1
    ) AND status='queued'
    RETURNING *, ? AS claim_token
    """
    rows = _rows(d1._request({"sql": sql, "params": [now, now, MAX_ATTEMPTS, token]}))
    return rows[0] if rows else None


def _finish(order_id: str, status: str, *, report: Dict[str, Any] | None = None, evidence_count: int = 0, error: str = "") -> None:
    d1._request({
        "sql": "UPDATE lumen_paid_fulfillment_jobs SET status=?, updated_at=?, report_json=?, evidence_count=?, last_error=?, claimed_at=NULL WHERE order_id=? AND status='researching'",
        "params": [status, _now(), json.dumps(report, ensure_ascii=False, separators=(",", ":")) if report else None, int(evidence_count), _text(error, 600) or None, order_id],
    })


def run_once() -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "version": VERSION,
        "status": "ok",
        "synced": 0,
        "claimed": False,
        "order_id": None,
        "queries": 0,
        "evidence": 0,
        "result": "idle",
        "outgoing_spend": False,
        "updated_at": _now(),
    }
    try:
        _ensure_schema()
        report["synced"] = _sync_paid_orders()
        _reclaim_stale()
        job = _claim_one()
        if not job:
            return report
        report["claimed"] = True
        report["order_id"] = job.get("order_id")
        item_id = _text(job.get("item_id"), 100)
        if item_id not in PRODUCTS:
            _finish(_text(job.get("order_id"), 100), "blocked", error="unsupported_paid_item")
            report["status"] = "blocked"
            report["result"] = "unsupported_paid_item"
            return report

        requirement = _text(job.get("requirement"), 8000)
        queries = _queries(item_id, requirement)
        all_results: List[Dict[str, Any]] = []
        for query in queries:
            all_results.extend(_search(query))
        evidence = _clean_evidence(all_results)
        report["queries"] = len(queries)
        report["evidence"] = len(evidence)

        if len(evidence) < MIN_EVIDENCE:
            attempts = int(job.get("attempts") or 1)
            next_status = "blocked_insufficient_evidence" if attempts >= MAX_ATTEMPTS else "queued"
            _finish(_text(job.get("order_id"), 100), next_status, evidence_count=len(evidence), error=f"insufficient_public_evidence:{len(evidence)}")
            report["status"] = "waiting_evidence" if next_status == "queued" else "blocked"
            report["result"] = next_status
            return report

        structured = _build_report(job, evidence, queries)
        _finish(_text(job.get("order_id"), 100), "report_ready", report=structured, evidence_count=len(evidence))
        report["result"] = "report_ready"
        report["report_id"] = structured.get("report_id")
        return report
    except Exception as exc:
        report["status"] = "degraded_fail_closed"
        report["result"] = f"{type(exc).__name__}: {str(exc)[:400]}"
        print({"paid_fulfillment_runtime": report}, flush=True)
        return report


if __name__ == "__main__":
    print(json.dumps(run_once(), ensure_ascii=False, default=str))
