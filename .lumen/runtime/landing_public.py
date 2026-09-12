from __future__ import annotations

import os

from fastapi.responses import HTMLResponse

from app import app

PUBLIC_CONTACT = os.getenv("LUMEN_PUBLIC_CONTACT_EMAIL", "Lumenstock2026@gmail.com").strip()


LANDING_HTML = r'''<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="description" content="LUMEN brinda servicios de inteligencia comercial B2B, sourcing de proveedores, búsqueda de oportunidades, gestión de cotizaciones y coordinación comercial entre empresas." />
  <meta name="robots" content="index,follow" />
  <title>LUMEN | Inteligencia comercial B2B y sourcing</title>
  <style>
    :root{--bg:#071019;--panel:#0d1822;--panel2:#111f2b;--text:#edf6fb;--muted:#9eb1bd;--line:#1c3545;--accent:#d8ff66;--accent2:#8ed7ff}
    *{box-sizing:border-box} html{scroll-behavior:smooth} body{margin:0;background:linear-gradient(180deg,#061019 0%,#09131c 55%,#071019 100%);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;line-height:1.55}
    a{color:inherit}.wrap{max-width:1140px;margin:0 auto;padding:0 24px}.nav{height:78px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #ffffff10}.brand{font-weight:900;letter-spacing:.22em;font-size:22px}.nav a{text-decoration:none;color:var(--muted);font-weight:700;font-size:14px}.hero{padding:92px 0 72px;display:grid;grid-template-columns:1.25fr .75fr;gap:44px;align-items:center}.eyebrow{color:var(--accent);text-transform:uppercase;letter-spacing:.15em;font-weight:800;font-size:12px}.hero h1{font-size:clamp(42px,6vw,72px);line-height:1.02;margin:14px 0 22px;letter-spacing:-.045em}.hero p{color:var(--muted);font-size:19px;max-width:760px}.cta{display:inline-block;margin-top:20px;background:var(--accent);color:#111820;text-decoration:none;font-weight:900;padding:14px 20px;border-radius:10px}.proof{background:linear-gradient(145deg,var(--panel2),#0b151e);border:1px solid var(--line);border-radius:24px;padding:26px}.proof strong{font-size:28px;display:block;margin-bottom:8px}.proof p{margin:0;color:var(--muted)}.section{padding:68px 0}.section h2{font-size:34px;margin:0 0 14px}.section .lead{color:var(--muted);max-width:780px;margin-bottom:32px}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.card{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:24px}.card h3{margin:0 0 10px;font-size:19px}.card p{margin:0;color:var(--muted)}.steps{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.step{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px}.num{color:var(--accent2);font-weight:900;font-size:13px;letter-spacing:.12em}.step h3{margin:8px 0;font-size:17px}.step p{color:var(--muted);font-size:14px;margin:0}.about{display:grid;grid-template-columns:1fr 1fr;gap:20px}.pill{display:inline-block;border:1px solid var(--line);background:#0d1922;border-radius:999px;padding:7px 11px;margin:5px 5px 0 0;color:#c9d8e2;font-size:13px}.contact{background:linear-gradient(135deg,#112532,#0b171f);border:1px solid #2c4b5c;border-radius:22px;padding:30px}.contact a{color:var(--accent);font-weight:800}.fine{color:#728896;font-size:12px;margin-top:22px}.footer{border-top:1px solid #ffffff10;padding:28px 0 44px;color:#79909e;font-size:13px}@media(max-width:820px){.hero,.about{grid-template-columns:1fr}.steps{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr}.hero{padding-top:58px}}@media(max-width:540px){.wrap{padding:0 18px}.steps{grid-template-columns:1fr}.nav{height:68px}.hero h1{font-size:42px}.hero p{font-size:17px}}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="nav">
      <div class="brand">LUMEN</div>
      <a href="#contacto">Contacto comercial</a>
    </header>

    <main>
      <section class="hero">
        <div>
          <div class="eyebrow">Inteligencia comercial B2B · Argentina</div>
          <h1>Conectamos demanda empresarial con oferta confiable.</h1>
          <p>LUMEN es un proyecto de servicios comerciales B2B orientado a investigar oportunidades, identificar compradores y proveedores, organizar cotizaciones y coordinar procesos comerciales con evidencia verificable.</p>
          <a class="cta" href="#contacto">Hablar con LUMEN</a>
        </div>
        <aside class="proof">
          <strong>Enfoque B2B</strong>
          <p>Trabajamos sobre necesidades comerciales reales, fuentes públicas y contactos corporativos. La prioridad es reducir incertidumbre antes de avanzar con una operación.</p>
        </aside>
      </section>

      <section class="section" id="servicios">
        <h2>Qué hacemos</h2>
        <p class="lead">Ayudamos a empresas a ordenar la búsqueda comercial y de abastecimiento, desde la identificación de una necesidad hasta la coordinación de una oportunidad concreta.</p>
        <div class="grid">
          <article class="card"><h3>Investigación de oportunidades</h3><p>Identificación y evaluación de señales públicas de demanda, necesidades de compra, sectores y empresas con potencial encaje comercial.</p></article>
          <article class="card"><h3>Sourcing de proveedores</h3><p>Búsqueda, comparación y preselección de proveedores según capacidad, evidencia comercial, condiciones y adecuación a la necesidad.</p></article>
          <article class="card"><h3>Gestión de cotizaciones</h3><p>Organización y normalización de información comercial para facilitar comparaciones de precio, alcance, plazo y condiciones.</p></article>
          <article class="card"><h3>Coordinación comercial B2B</h3><p>Preparación de contactos, seguimiento de conversaciones y soporte al desarrollo de oportunidades entre empresas compradoras y proveedoras.</p></article>
        </div>
      </section>

      <section class="section">
        <h2>Cómo trabajamos</h2>
        <p class="lead">El proceso prioriza trazabilidad, evidencia y control humano para compromisos vinculantes.</p>
        <div class="steps">
          <div class="step"><div class="num">01</div><h3>Detectar</h3><p>Buscamos una necesidad o oportunidad empresarial verificable.</p></div>
          <div class="step"><div class="num">02</div><h3>Validar</h3><p>Revisamos empresas, canales corporativos, requisitos y evidencia pública.</p></div>
          <div class="step"><div class="num">03</div><h3>Comparar</h3><p>Contrastamos alternativas de suministro y condiciones comerciales.</p></div>
          <div class="step"><div class="num">04</div><h3>Coordinar</h3><p>Acompañamos la conversación comercial hasta que exista una oportunidad concreta.</p></div>
        </div>
      </section>

      <section class="section about">
        <div class="card">
          <h2>Clientes y mercados</h2>
          <p class="lead">El foco inicial está en empresas, áreas de compras, mantenimiento, ingeniería, distribución y servicios técnicos que necesitan encontrar soluciones o proveedores.</p>
          <span class="pill">Argentina</span><span class="pill">Latinoamérica</span><span class="pill">Operaciones internacionales</span><span class="pill">Industria y servicios B2B</span>
        </div>
        <div class="card">
          <h2>Modelo de trabajo</h2>
          <p class="lead">LUMEN presta servicios de desarrollo comercial, investigación y coordinación B2B. No se presentan como realizadas operaciones que todavía no hayan sido verificadas y documentadas.</p>
          <p class="fine">Los términos económicos, medios de cobro y compromisos contractuales se definen específicamente para cada operación y requieren validación correspondiente.</p>
        </div>
      </section>

      <section class="section" id="contacto">
        <div class="contact">
          <div class="eyebrow">Contacto</div>
          <h2>Consultas comerciales</h2>
          <p>Para oportunidades B2B, sourcing de proveedores o coordinación comercial:</p>
          <p><a href="mailto:__CONTACT__">__CONTACT__</a></p>
          <p class="fine">LUMEN · Servicios de inteligencia comercial y sourcing B2B · Argentina</p>
        </div>
      </section>
    </main>

    <footer class="footer">© 2026 LUMEN. Servicios comerciales B2B.</footer>
  </div>
</body>
</html>'''


def _render() -> HTMLResponse:
    safe_contact = PUBLIC_CONTACT.replace("<", "").replace(">", "").replace('"', "")
    return HTMLResponse(LANDING_HTML.replace("__CONTACT__", safe_contact))


@app.get("/lumen", response_class=HTMLResponse, include_in_schema=False)
def lumen_public_landing():
    return _render()


@app.get("/about", response_class=HTMLResponse, include_in_schema=False)
def lumen_public_about():
    return _render()
