#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

function arg(name, fallback='') {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i+1] ? process.argv[i+1] : fallback;
}
function esc(v='') {
  return String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function arr(v) { return Array.isArray(v) ? v : []; }
function titleize(v='') { return String(v).replaceAll('_',' ').replace(/\b\w/g, m=>m.toUpperCase()); }
function formatDate(v='') {
  const raw=String(v || '');
  const m=raw.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : raw;
}

const inputPath = arg('input');
const outputPath = arg('output', 'lumen-report.html');
const contractsPath = arg('templates', path.resolve('.lumen/contracts/delivery-templates.json'));
if (!inputPath) {
  console.error('Usage: node render_report.mjs --input report.json [--output report.html] [--templates delivery-templates.json]');
  process.exit(2);
}

const data = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
const defs = JSON.parse(fs.readFileSync(contractsPath, 'utf8'));
const key = data.template_key || data.product_slug || data.service_id || data.product_or_service_id;
let tier = 'full';
let tpl = defs.service_templates?.[key];
if (!tpl) {
  tpl = defs.micro_templates?.[key];
  if (tpl) tier = 'micro';
}
if (!tpl) {
  const service = Object.entries(defs.service_templates || {}).find(([id]) => id === data.service_id || id === data.product_or_service_id);
  if (service) { tpl = service[1]; tier='full'; }
}
if (!tpl) throw new Error(`Unknown delivery template: ${key}`);

const brand = defs.brand || {name:'LUMEN',descriptor:'B2B Intelligence'};
const meta = {
  report_id: data.report_id || 'LUMEN-DRAFT',
  client: data.client || data.company || 'Cliente',
  generated_at: data.generated_at || new Date().toISOString(),
  evidence_cutoff: data.evidence_cutoff || data.generated_at || new Date().toISOString(),
  request: data.client_request || data.request || 'No informado'
};
const confidence = data.confidence || 'no determinada';
const recommendation = data.recommendation || data.conclusion || 'Revisar los hallazgos y próximos pasos.';

function badges() {
  const metrics = arr(tpl.hero_metrics).map(k => {
    const val = data.metrics?.[k] ?? data[k];
    if (val === undefined || val === null || val === '') return '';
    return `<div class="metric"><span>${esc(titleize(k))}</span><strong>${esc(val)}</strong></div>`;
  }).filter(Boolean).join('');
  return metrics ? `<section class="metrics">${metrics}</section>` : '';
}
function bulletSection(title, items, cls='') {
  const list = arr(items).filter(Boolean);
  if (!list.length) return '';
  return `<section class="section ${cls}"><h2>${esc(title)}</h2><ul>${list.map(x=>`<li>${esc(typeof x === 'string' ? x : x.text || x.title || JSON.stringify(x))}</li>`).join('')}</ul></section>`;
}
function paragraphs(title, value) {
  if (!value) return '';
  const ps = Array.isArray(value) ? value : [value];
  return `<section class="section"><h2>${esc(title)}</h2>${ps.map(p=>`<p>${esc(typeof p === 'string' ? p : p.text || JSON.stringify(p))}</p>`).join('')}</section>`;
}
function renderTables() {
  const tables = arr(data.tables);
  if (!tables.length) return '';
  return tables.map(t => {
    const cols = arr(t.columns).length ? t.columns : arr(tpl.primary_table);
    const rows = arr(t.rows);
    return `<section class="section"><h2>${esc(t.title || 'Comparación')}</h2><div class="tablewrap"><table><thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${cols.map((c,i)=>`<td>${esc(Array.isArray(r) ? r[i] ?? '' : r[c] ?? r[String(c).toLowerCase().replace(/\s+/g,'_')] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div></section>`;
  }).join('');
}
function renderEvidence() {
  const items = arr(data.evidence);
  if (!items.length) return '';
  return `<section class="section"><h2>Evidencia y fuentes</h2><div class="evidence">${items.map((e,i)=>`<article><div class="source-index">${i+1}</div><div><strong>${esc(e.title || e.source || 'Fuente')}</strong>${e.url?`<div><a href="${esc(e.url)}">${esc(e.url)}</a></div>`:''}${e.note?`<p>${esc(e.note)}</p>`:''}<small>Consultado: ${esc(e.observed_at || meta.evidence_cutoff)}</small></div></article>`).join('')}</div></section>`;
}
function renderRisks() {
  const risks = arr(data.risks);
  if (!risks.length) return '';
  return `<section class="section"><h2>Riesgos y gaps</h2><div class="riskgrid">${risks.map(r=>`<article class="risk ${esc(r.level || 'no_determinado')}"><span>${esc((r.level || 'no determinado').toUpperCase())}</span><strong>${esc(r.title || 'Observación')}</strong><p>${esc(r.detail || '')}</p></article>`).join('')}</div></section>`;
}
function renderFindings() {
  const findings = arr(data.findings || data.key_findings);
  if (!findings.length) return '';
  return `<section class="section"><h2>Hallazgos clave</h2><div class="findings">${findings.map((f,i)=>`<article><span>${String(i+1).padStart(2,'0')}</span><div><strong>${esc(typeof f === 'string' ? f : f.title || 'Hallazgo')}</strong>${typeof f === 'object' && f.detail?`<p>${esc(f.detail)}</p>`:''}${typeof f === 'object' && f.confidence?`<small>Confianza: ${esc(f.confidence)}</small>`:''}</div></article>`).join('')}</div></section>`;
}

const analysisBlocks = arr(tpl.analysis_blocks).map(k => paragraphs(titleize(k), data.analysis?.[k] ?? data[k])).join('');
const executive = data.executive_summary || data.answer || data.summary || recommendation;
const methodology = data.methodology || (tier === 'micro' ? 'Revisión rápida de información proporcionada por el cliente y fuentes públicas accesibles al momento del análisis.' : 'Investigación estructurada sobre el requerimiento del cliente, contraste de fuentes públicas y separación entre evidencia, inferencia y recomendación.');
const limitations = arr(data.limitations).length ? data.limitations : ['El análisis se limita a la información aportada y a fuentes públicas accesibles en la fecha indicada.', 'La ausencia de una señal pública no prueba la ausencia del hecho subyacente.', 'LUMEN no garantiza resultados comerciales, solvencia, adjudicaciones, stock, precio futuro ni cumplimiento de terceros.'];

const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(tpl.title)} · ${esc(brand.name)}</title><style>
:root{--ink:#0b1320;--muted:#5d6b7a;--line:#dbe3ea;--soft:#f5f8fa;--accent:#b5ef42;--accent2:#74c7ec;--navy:#071019;--white:#fff}*{box-sizing:border-box}body{margin:0;color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;background:#eef3f6;line-height:1.5}.report{max-width:980px;margin:32px auto;background:#fff;box-shadow:0 18px 70px #10203020}.cover{min-height:520px;background:linear-gradient(145deg,#061019,#0e2333);color:#fff;padding:64px;display:flex;flex-direction:column;justify-content:space-between}.micro-cover{min-height:0;padding:38px 64px 30px;display:block}.micro-cover h1{font-size:40px;margin:24px 0 10px}.micro-cover .question{display:none}.micro-cover .covermeta{grid-template-columns:repeat(4,minmax(0,1fr));margin-top:24px;gap:12px}.micro-cover .covermeta strong{font-size:12px}.brand{letter-spacing:.22em;font-weight:900;font-size:14px}.descriptor{color:#9fb3c1;font-size:13px;margin-top:6px}.cover h1{font-size:58px;line-height:.98;margin:36px 0 18px;letter-spacing:-.04em}.cover .question{max-width:720px;color:#c3d2db;font-size:20px}.covermeta{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;margin-top:44px}.covermeta div{border-top:1px solid #ffffff25;padding-top:10px}.covermeta span{display:block;color:#8ea3b1;font-size:12px;text-transform:uppercase;letter-spacing:.08em}.covermeta strong{display:block;margin-top:4px}.body{padding:56px 64px 72px}.executive{border-left:6px solid var(--accent);background:#f7fbe9;padding:26px 28px;margin-bottom:32px}.executive h2{margin:0 0 10px}.executive p{font-size:20px;margin:0}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:28px 0}.metric{border:1px solid var(--line);border-radius:14px;padding:16px}.metric span{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}.metric strong{display:block;font-size:22px;margin-top:6px}.section{padding:26px 0;border-top:1px solid var(--line)}.section h2{font-size:24px;margin:0 0 14px}.section p{margin:8px 0;color:#263748}.section li{margin:7px 0}.request{background:var(--soft);padding:20px 22px;border-radius:14px;margin-bottom:28px}.request span{display:block;color:var(--muted);font-size:12px;text-transform:uppercase}.request p{font-size:17px;margin:6px 0 0}.findings{display:grid;gap:12px}.findings article{display:grid;grid-template-columns:46px 1fr;gap:12px;padding:16px;border:1px solid var(--line);border-radius:14px}.findings article>span{font-size:24px;font-weight:900;color:#9abf39}.findings p{margin:4px 0}.findings small{color:var(--muted)}.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px}table{width:100%;border-collapse:collapse;font-size:13px}th{background:#0b1823;color:#fff;text-align:left;padding:12px}td{padding:11px 12px;border-top:1px solid var(--line);vertical-align:top}tr:nth-child(even) td{background:#f9fbfc}.riskgrid{display:grid;gap:12px}.risk{border:1px solid var(--line);border-left:5px solid #9aa6b2;border-radius:12px;padding:14px 16px}.risk span{font-size:10px;letter-spacing:.08em;color:var(--muted);display:block}.risk strong{display:block;margin:4px 0}.risk p{margin:0}.risk.alto{border-left-color:#e25050}.risk.medio{border-left-color:#e2a23e}.risk.bajo{border-left-color:#54a96b}.evidence{display:grid;gap:10px}.evidence article{display:grid;grid-template-columns:34px 1fr;gap:12px;padding:14px;background:var(--soft);border-radius:10px}.source-index{width:28px;height:28px;border-radius:50%;background:#e8f6bd;display:flex;align-items:center;justify-content:center;font-weight:800}.evidence a{color:#146a96;word-break:break-all}.evidence p{margin:5px 0}.evidence small{color:var(--muted)}.recommendation{background:#0b1823;color:#fff;border-radius:18px;padding:28px;margin-top:30px}.recommendation span{color:var(--accent);font-size:12px;text-transform:uppercase;letter-spacing:.1em;font-weight:800}.recommendation h2{margin:8px 0 10px;font-size:28px}.recommendation p{margin:0;color:#d3dee5;font-size:18px}.footer{padding:22px 64px 34px;color:#71808d;font-size:11px;border-top:1px solid var(--line)}@media(max-width:700px){.report{margin:0}.cover,.body,.footer{padding-left:24px;padding-right:24px}.cover h1{font-size:42px}.covermeta{grid-template-columns:1fr}}@media print{body{background:#fff}.report{box-shadow:none;margin:0;max-width:none}.section,.risk,.findings article,.tablewrap{break-inside:avoid}.cover:not(.micro-cover){break-after:page}.micro-cover{break-after:auto;page-break-after:auto}.body{padding-top:34px}@page{size:A4;margin:12mm}}
</style></head><body><article class="report"><header class="${tier==='micro'?'cover micro-cover':'cover'}"><div><div class="brand">${esc(brand.name)}</div><div class="descriptor">${esc(brand.descriptor || '')}</div><h1>${esc(tpl.title)}</h1><p class="question">${esc(tpl.decision_question || data.subtitle || '')}</p></div><div class="covermeta"><div><span>Cliente</span><strong>${esc(meta.client)}</strong></div><div><span>ID de informe</span><strong>${esc(meta.report_id)}</strong></div><div><span>Fecha</span><strong>${esc(formatDate(meta.generated_at))}</strong></div><div><span>Corte de evidencia</span><strong>${esc(formatDate(meta.evidence_cutoff))}</strong></div></div></header><main class="body"><div class="request"><span>Pedido del cliente</span><p>${esc(meta.request)}</p></div><section class="executive"><h2>${tier==='micro'?'Respuesta ejecutiva':'Resumen ejecutivo'}</h2><p>${esc(executive)}</p><small>Confianza: ${esc(confidence)}</small></section>${badges()}${renderFindings()}${analysisBlocks}${renderTables()}${renderRisks()}${renderEvidence()}${paragraphs('Metodología', methodology)}${bulletSection('Limitaciones', limitations)}${bulletSection('Próximos pasos', data.next_steps)}<section class="recommendation"><span>${esc(tpl.final_callout || 'Recomendación')}</span><h2>Conclusión</h2><p>${esc(recommendation)}</p></section></main><footer class="footer">${esc(brand.name)} · ${esc(brand.descriptor || '')} · Informe generado a partir de información del cliente y evidencia pública trazable. Este documento no constituye asesoramiento legal, contable, financiero ni garantía de resultado.</footer></article></body></html>`;

fs.mkdirSync(path.dirname(outputPath), {recursive:true});
fs.writeFileSync(outputPath, html, 'utf8');
console.log(JSON.stringify({ok:true,template:key,tier,output:outputPath,report_id:meta.report_id}));
