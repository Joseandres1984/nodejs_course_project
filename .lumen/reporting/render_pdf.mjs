#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';
import { chromium } from 'playwright';
import { PDFDocument } from 'pdf-lib';

function arg(name, fallback='') {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}
function fail(message, detail='') {
  console.error(JSON.stringify({ ok:false, error:message, detail }));
  process.exit(1);
}

const inputPath = path.resolve(arg('input'));
const outputPath = path.resolve(arg('output', 'lumen-report.pdf'));
const reportId = arg('report-id', 'LUMEN-REPORT');
const title = arg('title', 'LUMEN B2B Intelligence Report');
const chromiumPath = arg('chromium', process.env.CHROMIUM_PATH || '');

if (!arg('input')) fail('missing_input', 'Use --input report.html');
if (!fs.existsSync(inputPath)) fail('input_not_found', inputPath);
if (!inputPath.toLowerCase().endsWith('.html')) fail('invalid_input', 'Input must be HTML');
if (!outputPath.toLowerCase().endsWith('.pdf')) fail('invalid_output', 'Output must end in .pdf');

fs.mkdirSync(path.dirname(outputPath), { recursive:true });
const rawPdf = `${outputPath}.chromium.tmp`;
const finalTmp = `${outputPath}.final.tmp`;
for (const p of [rawPdf, finalTmp]) { try { fs.unlinkSync(p); } catch {} }

const browserErrors = [];
let browser;
try {
  browser = await chromium.launch({
    headless:true,
    ...(chromiumPath ? { executablePath:chromiumPath } : {}),
    args:['--no-sandbox','--disable-dev-shm-usage','--font-render-hinting=medium'],
  });
  const page = await browser.newPage({ viewport:{ width:1240, height:1754 }, deviceScaleFactor:1 });
  page.on('pageerror', error => browserErrors.push(`pageerror:${String(error?.message || error)}`));
  page.on('console', msg => { if (msg.type() === 'error') browserErrors.push(`console:${msg.text()}`); });
  page.on('requestfailed', req => browserErrors.push(`request:${req.url()}:${req.failure()?.errorText || 'failed'}`));

  await page.goto(pathToFileURL(inputPath).href, { waitUntil:'load', timeout:30000 });
  await page.evaluate((id) => {
    const footer = document.querySelector('.footer');
    if (!footer) return;
    if ((footer.textContent || '').includes(id)) return;
    const marker = document.createElement('span');
    marker.className = 'report-id-visible';
    marker.textContent = ` · ID: ${id}`;
    footer.appendChild(marker);
  }, reportId);
  await page.evaluate(async () => { if (document.fonts?.ready) await document.fonts.ready; });
  await page.addStyleTag({ content:`
    * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
    .report-id-visible { overflow-wrap: anywhere !important; word-break: break-word !important; }
    @media print {
      html, body { width: 100% !important; margin: 0 !important; padding: 0 !important; }
      .report { width: 100% !important; max-width: none !important; margin: 0 !important; box-shadow: none !important; }
      .tablewrap { overflow: visible !important; max-width: 100% !important; }
      table { width: 100% !important; max-width: 100% !important; table-layout: fixed !important; border-collapse: collapse !important; }
      thead { display: table-header-group !important; }
      tfoot { display: table-footer-group !important; }
      tr, th, td, .risk, .findings article, .metric, .evidence article, .executive, .recommendation { break-inside: avoid !important; page-break-inside: avoid !important; }
      th, td { overflow-wrap: anywhere !important; word-break: break-word !important; hyphens: auto !important; }
      th { font-size: 9.5px !important; }
      td { font-size: 9.3px !important; line-height: 1.32 !important; }
      a { overflow-wrap: anywhere !important; word-break: break-all !important; }
      img, svg, canvas { max-width: 100% !important; height: auto !important; }
      .cover:not(.micro-cover) { min-height: 273mm !important; break-after: page !important; page-break-after: always !important; }
      .micro-cover { min-height: 0 !important; break-after: auto !important; page-break-after: auto !important; padding-top: 30px !important; padding-bottom: 24px !important; }
      .section h2 { break-after: avoid !important; page-break-after: avoid !important; }
    }
    @page { size: A4; margin: 12mm; }
  `});
  await page.emulateMedia({ media:'print' });

  const diagnostics = await page.evaluate(() => ({
    title:document.title,
    textLength:(document.body?.innerText || '').trim().length,
    scrollWidth:document.documentElement.scrollWidth,
    bodyWidth:document.body?.scrollWidth || 0,
    tables:[...document.querySelectorAll('table')].map(t => ({ rows:t.rows.length, width:t.scrollWidth })),
  }));
  if (diagnostics.textLength < 120) fail('report_too_short', JSON.stringify(diagnostics));

  await page.pdf({
    path:rawPdf,
    format:'A4',
    printBackground:true,
    preferCSSPageSize:true,
    displayHeaderFooter:false,
    tagged:true,
    outline:true,
  });
  await browser.close();
  browser = null;

  if (browserErrors.length) fail('browser_render_error', browserErrors.slice(0,8).join(' | '));
  if (!fs.existsSync(rawPdf) || fs.statSync(rawPdf).size < 12000) fail('pdf_generation_failed', 'Chromium output missing or too small');

  const bytes = fs.readFileSync(rawPdf);
  const pdf = await PDFDocument.load(bytes, { updateMetadata:false });
  pdf.setTitle(title);
  pdf.setAuthor('LUMEN B2B Intelligence');
  pdf.setSubject(`LUMEN report ${reportId}`);
  pdf.setCreator('LUMEN Report Engine');
  pdf.setProducer('LUMEN Report Engine / Chromium / pdf-lib');
  pdf.setKeywords(['LUMEN','B2B Intelligence',reportId]);
  pdf.setCreationDate(new Date());
  pdf.setModificationDate(new Date());
  const finalBytes = await pdf.save({ useObjectStreams:true, addDefaultPage:false });
  fs.writeFileSync(finalTmp, finalBytes);
  if (finalBytes.length < 12000 || Buffer.from(finalBytes).subarray(0,5).toString() !== '%PDF-') fail('invalid_final_pdf', 'Final PDF failed signature/size check');
  fs.renameSync(finalTmp, outputPath);
  fs.unlinkSync(rawPdf);

  console.log(JSON.stringify({
    ok:true,
    output:outputPath,
    report_id:reportId,
    title,
    bytes:fs.statSync(outputPath).size,
    pages:pdf.getPageCount(),
    diagnostics,
  }));
} catch (error) {
  try { if (browser) await browser.close(); } catch {}
  for (const p of [rawPdf, finalTmp]) { try { fs.unlinkSync(p); } catch {} }
  fail('render_pdf_failed', String(error?.stack || error));
}
