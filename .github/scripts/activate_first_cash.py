from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    if new in text:
        return False
    if old not in text:
        raise SystemExit(f"expected anchor missing in {path}: {old[:120]}")
    p.write_text(text.replace(old, new, 1))
    return True


replace_once(
    ".lumen/a2a-worker/worker.js",
    '{ id:"MP-SUPPLIER-SNAPSHOT", name:"Supplier Snapshot", price_usd:5, service_id:"SRV-SUPPLIERCHECK", billing:"per_request", desc:"Fast supplier identity and official-channel snapshot for one named company or domain." }',
    '{ id:"MP-SUPPLIER-SNAPSHOT", name:"Supplier Snapshot", price_usd:1, service_id:"SRV-SUPPLIERCHECK", billing:"per_request", desc:"FIRST CASH entry offer: fast supplier identity and official-channel signal for one named company or domain." }',
)

replace_once(
    ".lumen/x402-worker/worker-v2.js",
    '"supplier-snapshot": { id:"MP-SUPPLIER-SNAPSHOT", name:"Supplier Snapshot", price_usd:5, service_id:"SRV-SUPPLIERCHECK" }',
    '"supplier-snapshot": { id:"MP-SUPPLIER-SNAPSHOT", name:"Supplier Snapshot", price_usd:1, service_id:"SRV-SUPPLIERCHECK" }',
)

replace_once(
    ".lumen/a2a-worker/proposal-engine.js",
    '"MP-SUPPLIER-SNAPSHOT": { name: "Supplier Snapshot", priceUsd: 5, outcome: "a compact supplier verification snapshot" }',
    '"MP-SUPPLIER-SNAPSHOT": { name: "Supplier Snapshot", priceUsd: 1, outcome: "a compact supplier identity and official-channel signal for one named company or domain" }',
)

wrangler = Path(".lumen/a2a-worker/wrangler.toml")
text = wrangler.read_text()
if 'LUMEN_FIRST_CASH_MODE = "true"' not in text:
    anchor = 'A2A_AUTONOMOUS_CONVERSION_CLOSE = "true"\n'
    if anchor not in text:
        raise SystemExit("first cash wrangler anchor missing")
    wrangler.write_text(text.replace(anchor, anchor + 'LUMEN_FIRST_CASH_MODE = "true"\n', 1))

entry = Path(".lumen/a2a-worker/opportunity-entry.js")
text = entry.read_text()
if "const firstCashModeActive" not in text:
    old = '      const preferredExternalAction = portfolio?.recommendedExternalAction || "NONE";'
    new = (
        '      const firstCashModeActive = String(env?.LUMEN_FIRST_CASH_MODE || "").toLowerCase() === "true" '
        '&& Number(portfolio?.metrics?.verifiedRevenueUsd || 0) < 1;\n'
        '      const preferredExternalAction = firstCashModeActive ? "FIRST_CASH" : (portfolio?.recommendedExternalAction || "NONE");'
    )
    if old not in text:
        raise SystemExit("opportunity-entry FIRST CASH anchor missing")
    entry.write_text(text.replace(old, new, 1))

print("FIRST_CASH_MODE_PATCH_OK")
