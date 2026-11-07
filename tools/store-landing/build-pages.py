"""Build the two static, product-specific LUMEN landing pages."""
from pathlib import Path
from html import escape

ROOT = Path(__file__).resolve().parents[2] / "lumen-store"
ORIGIN = "https://lumen-store-6ahq.onrender.com"
AMAZON = "https://www.amazon.com/dp/B0BZYBSRNF?tag=lumenb2b-20"
COPY = {
    "es": {
        "lang": "es-US", "path": "/", "other": "/en/", "switch": "English", "label": "Español",
        "title": "Owala FreeSip 32 oz · Dos formas de beber | LUMEN STORE",
        "meta": "Conoce la Owala FreeSip de 32 oz: pajita integrada, boquilla para beber a tragos y tapa con cierre. Revisa el precio actual y compra en Amazon.com.",
        "top": "Selección para EE. UU.", "buywhere": "Compra directamente en Amazon.com", "nav": "Conoce FreeSip", "skip": "Ir al producto",
        "eyebrow": "UN FAVORITO PARA TU DÍA A DÍA", "h1": "Dos formas de beber.<br><em>Un solo favorito.</em>",
        "lead": "A sorbos en el escritorio. A tragos después de entrenar. La Owala FreeSip combina las dos formas en una botella que va contigo.",
        "cta": "Ver precio en Amazon", "ctasmall": "Ver en Amazon", "detail": "Descubre cómo funciona", "affiliate": "Enlace de afiliado: podemos recibir una comisión por compras que cumplan los requisitos.",
        "spec1": "32 oz de capacidad", "spec2": "Acero inoxidable", "spec3": "Color Denim", "imagealt": "Owala FreeSip de 32 oz en color Denim: botella azul con tapa y asa en tonos verde y azul",
        "caption": "Tu botella. A tu manera.", "photolabel": "FreeSip® · 32 oz · Denim", "featurelabel": "PAJITA + BOQUILLA",
        "buytitle": "Elige con todo claro", "buy1": "Producto concreto", "buy1text": "El enlace abre la ficha de esta Owala FreeSip.", "buy2": "Precio actualizado", "buy2text": "Consulta las condiciones vigentes en Amazon.", "buy3": "Compra en Amazon", "buy3text": "Revisa vendedor, envío y devoluciones allí.",
        "howkicker": "EL DETALLE QUE CAMBIA LA RUTINA", "howtitle": "Tu día cambia.<br>Tu forma de beber, también.", "howlead": "La boquilla FreeSip ofrece dos maneras de tomar agua, sin cambiar de botella.",
        "siptitle": "A sorbos", "siptext": "Mantén la botella vertical y bebe por la pajita integrada. Un gesto cómodo para trabajar o estudiar.", "swigtitle": "A tragos", "swigtext": "Inclina la botella y bebe por la abertura de la boquilla. Tú eliges el ritmo.",
        "featureskicker": "BIEN PENSADA, HASTA EN LOS DETALLES", "featurestitle": "Lista para acompañarte.",
        "features": [("Agua fría por más tiempo", "El fabricante indica hasta 24 horas de conservación del frío en la versión de acero inoxidable."), ("Tapa con botón y cierre", "La cubierta protege la boquilla. El asa también actúa como bloqueo cuando está cerrada."), ("Espacio para el hielo", "La apertura amplia facilita añadir hielo y limpiar el interior."), ("Cuidado sencillo", "Lava el cuerpo a mano. La tapa es apta para la bandeja superior del lavavajillas.")],
        "fitkicker": "PARA ELEGIR BIEN", "fittitle": "¿Va con tu rutina?", "fittext": "Una opción para llevar agua fría al trabajo, al gimnasio o en tus salidas.", "fitnote": "Ten en cuenta: el fabricante desaconseja usar FreeSip de acero inoxidable con líquidos calientes, carbonatados o perecederos. Confirma las medidas si necesitas que encaje en un portavasos.",
        "finalkicker": "OWALA FREESIP · 32 OZ · DENIM", "finaltitle": "Hazle un lugar<br>a tu próximo favorito.", "finaltext": "Conoce el precio actual, las opiniones de compradores y las opciones de entrega en la ficha de Amazon.",
        "faqtitle": "Antes de elegir, lo esencial.", "faqs": [("¿Dónde se realiza la compra?", "En Amazon.com. LUMEN STORE recomienda productos y no procesa el pago. Amazon y el vendedor gestionan las condiciones de la operación, la entrega y las devoluciones."), ("¿Qué modelo abre el enlace?", "Owala FreeSip de acero inoxidable, 32 oz, color Denim; ASIN B0BZYBSRNF. Comprueba el modelo y la variante seleccionados en la ficha antes de comprar."), ("¿El precio incluye algún descuento?", "El precio y cualquier promoción vigente se consultan en Amazon. Esta página no garantiza una rebaja, un cupón ni disponibilidad. Las condiciones pueden variar por vendedor, variante o fecha."), ("¿Puedo comprar desde Argentina u otro país?", "La selección está orientada a compras en Amazon.com para Estados Unidos. Los envíos internacionales, sus impuestos y costos dependen del producto, vendedor y dirección. Verifica el total en Amazon antes de confirmar.")],
        "privacy": "Privacidad y medición", "privacytext": "Usamos PostHog para contar visitas e interacciones con los enlaces. La medición no graba sesiones, no crea perfiles personales y usa un identificador temporal en la memoria de esta página. No enviamos el texto completo de la URL ni datos de formularios. Respetamos las señales Do Not Track y Global Privacy Control. Puedes desactivar la medición con el botón siguiente. Al abrir Amazon se aplican sus políticas y tecnologías de afiliación.", "optout": "Desactivar medición", "disabled": "Medición desactivada", "catalog": "Explorar el catálogo", "source": "Características del fabricante", "footer": "LUMEN STORE es una selección independiente de productos afiliados. Owala y FreeSip son marcas de sus respectivos titulares. Precio, disponibilidad, envío y condiciones se confirman en Amazon.",
        "amazonstatement": "Como Afiliado de Amazon, LUMEN STORE obtiene ingresos por compras que cumplen los requisitos."
    },
    "en": {
        "lang": "en-US", "path": "/en/", "other": "/", "switch": "Español", "label": "English",
        "title": "Owala FreeSip 32 oz · Two ways to drink | LUMEN STORE", "meta": "Meet the 32 oz Owala FreeSip: a built-in straw, a sip-or-swig spout and a locking lid. Check the current price and shop on Amazon.com.",
        "top": "Selected for U.S. shoppers", "buywhere": "Shop directly on Amazon.com", "nav": "Meet FreeSip", "skip": "Skip to product", "eyebrow": "A LITTLE UPGRADE FOR YOUR EVERYDAY", "h1": "Two ways to drink.<br><em>One everyday favorite.</em>", "lead": "Sip at your desk. Swig after your workout. The Owala FreeSip brings both ways to drink into one bottle that goes with you.",
        "cta": "Check price on Amazon", "ctasmall": "View on Amazon", "detail": "See how it works", "affiliate": "Affiliate link: we may earn a commission from qualifying purchases.", "spec1": "32 oz capacity", "spec2": "Stainless steel", "spec3": "Denim color", "imagealt": "Owala FreeSip 32 oz in Denim: a blue bottle with a blue and mint lid and carry loop", "caption": "Your bottle. Your way.", "photolabel": "FreeSip® · 32 oz · Denim", "featurelabel": "SIP + SWIG",
        "buytitle": "Know before you go", "buy1": "A specific product", "buy1text": "The link opens this Owala FreeSip listing.", "buy2": "Current pricing", "buy2text": "Check the latest terms on Amazon.", "buy3": "Shop on Amazon", "buy3text": "Review the seller, shipping and returns there.",
        "howkicker": "ONE CLEVER EVERYDAY DETAIL", "howtitle": "Your day changes.<br>So can the way you drink.", "howlead": "The FreeSip spout gives you two ways to drink water without switching bottles.", "siptitle": "Take a sip", "siptext": "Keep the bottle upright and use the built-in straw. An easy way to drink while working or studying.", "swigtitle": "Take a swig", "swigtext": "Tilt the bottle and drink through the spout opening. Set your own pace.",
        "featureskicker": "THOUGHTFUL, DOWN TO THE DETAILS", "featurestitle": "Ready to tag along.", "features": [("Cold water, longer", "The manufacturer states up to 24 hours cold for the stainless-steel version."), ("Push-button locking lid", "The cover protects the spout. The carry loop also serves as a lock when closed."), ("Room for ice", "The wide opening makes it easier to add ice and clean the inside."), ("Straightforward care", "Hand-wash the bottle. The lid is top-rack dishwasher safe.")],
        "fitkicker": "MAKE IT A GOOD FIT", "fittitle": "Does it fit your day?", "fittext": "An option for taking cold water to work, the gym or your next day out.", "fitnote": "Keep in mind: the manufacturer advises against using the stainless-steel FreeSip with hot, carbonated or perishable liquids. Check the dimensions if cup-holder fit matters to you.",
        "finalkicker": "OWALA FREESIP · 32 OZ · DENIM", "finaltitle": "Meet your next<br>everyday favorite.", "finaltext": "See the current price, customer reviews and delivery options on the Amazon product page.",
        "faqtitle": "A few things to know first.", "faqs": [("Where do I complete my purchase?", "On Amazon.com. LUMEN STORE recommends products and does not process payments. Amazon and the seller manage the transaction terms, delivery and returns."), ("Which model does the link open?", "The Owala FreeSip stainless-steel bottle, 32 oz, Denim; ASIN B0BZYBSRNF. Confirm the selected model and variant on the product page before buying."), ("Is there a guaranteed discount?", "Check Amazon for the current price and any applicable promotion. This page does not guarantee a discount, coupon or availability. Terms can change by seller, variant or date."), ("Can I order outside the United States?", "This selection is intended for U.S. shoppers on Amazon.com. International shipping, taxes and costs depend on the product, seller and delivery address. Review the total on Amazon before you order.")],
        "privacy": "Privacy and measurement", "privacytext": "We use PostHog to count visits and link interactions. Measurement does not record sessions or create personal profiles, and uses a temporary identifier in this page's memory. We do not send the full URL or form data. We respect Do Not Track and Global Privacy Control signals. You can disable measurement below. Amazon's policies and affiliate technologies apply when you open Amazon.", "optout": "Disable measurement", "disabled": "Measurement disabled", "catalog": "Explore the catalog", "source": "Manufacturer specifications", "footer": "LUMEN STORE is an independent selection of affiliate products. Owala and FreeSip belong to their respective trademark owners. Confirm price, availability, shipping and terms on Amazon.", "amazonstatement": "As an Amazon Associate I earn from qualifying purchases."
    }
}

ARROW = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5"/></svg>'
def build(language):
    c = COPY[language]
    def cta(position, small=False):
        return f'<a class="buy-button" data-affiliate="B0BZYBSRNF" data-position="{position}" href="{AMAZON}" rel="sponsored nofollow noopener" target="_blank">{c["ctasmall"] if small else c["cta"]}{ARROW}</a>'
    features = ''.join(f'<li><span class="number">0{i+1}</span><div><h3>{escape(a)}</h3><p>{escape(b)}</p></div></li>' for i,(a,b) in enumerate(c['features']))
    faqs = ''.join(f'<details><summary>{escape(a)}<span aria-hidden="true">+</span></summary><p>{escape(b)}</p></details>' for a,b in c['faqs'])
    statement = c['amazonstatement']
    if language == 'es': statement += ' <span lang="en">As an Amazon Associate I earn from qualifying purchases.</span>'
    return f'''<!doctype html>
<html lang="{c['lang']}">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#122c34"><meta name="description" content="{escape(c['meta'], quote=True)}">
<meta name="referrer" content="strict-origin-when-cross-origin">
<title>{c['title']}</title><link rel="canonical" href="{ORIGIN}{c['path']}">
<link rel="alternate" hreflang="es-US" href="{ORIGIN}/"><link rel="alternate" hreflang="en-US" href="{ORIGIN}/en/"><link rel="alternate" hreflang="x-default" href="{ORIGIN}/">
<meta property="og:title" content="{c['title']}"><meta property="og:description" content="{escape(c['meta'], quote=True)}"><meta property="og:type" content="website"><meta property="og:url" content="{ORIGIN}{c['path']}"><meta property="og:image" content="{ORIGIN}/assets/B0BZYBSRNF.webp">
<link rel="icon" href="/assets/brand.webp"><link rel="preload" as="image" href="/assets/B0BZYBSRNF.webp"><link rel="stylesheet" href="/landing.css?v=20261104-freesip">
<script src="/landing.js?v=20261104-freesip" defer></script>
</head>
<body data-language="{language}" data-product="B0BZYBSRNF" data-page="freesip-v1">
<a href="#product" class="skip">{c['skip']}</a>
<div class="announcement"><span>{c['top']}</span><span class="announcement-divider">/</span><span>{c['buywhere']}</span></div>
<header class="header container"><a class="brand" href="{c['path']}" aria-label="LUMEN STORE"><img src="/assets/brand.webp" width="42" height="44" alt=""><span>LUMEN<small>STORE</small></span></a><nav aria-label="Navigation"><a class="nav-about" href="#how">{c['nav']}</a><a class="language" href="{c['other']}" data-language-switch hreflang="{'en-US' if language == 'es' else 'es-US'}">{c['switch']} <span aria-hidden="true">↗</span></a></nav></header>
<main>
<section class="hero container" id="product" aria-labelledby="headline"><div class="hero-copy"><p class="eyebrow"><span class="tiny-star" aria-hidden="true">✳</span>{c['eyebrow']}</p><h1 id="headline">{c['h1']}</h1><p class="hero-description">{c['lead']}</p><div class="product-meta"><span>{c['spec1']}</span><span>{c['spec2']}</span><span>{c['spec3']}</span></div><div class="hero-action">{cta('hero')}<a class="text-link" href="#how">{c['detail']} <span aria-hidden="true">↓</span></a></div><p class="affiliate-note">{c['affiliate']}</p></div>
<figure class="hero-photo"><div class="photo-header"><span>Owala<span class="reg">®</span></span><span class="pill">FreeSip®</span></div><div class="photo-stage"><span class="photo-word" aria-hidden="true">free<br>sip.</span><img src="/assets/B0BZYBSRNF.webp" width="420" height="420" alt="{c['imagealt']}" fetchpriority="high" decoding="async"><span class="feature-bubble">{c['featurelabel']}<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 17 11-11M7 6h10v10"/></svg></span></div><figcaption><span>{c['caption']}<small>{c['photolabel']}</small></span><span class="photo-symbol" aria-hidden="true">✳</span></figcaption></figure></section>
<section class="buy-strip" aria-label="{c['buytitle']}"><div class="container buy-strip-inner"><div><span class="small-icon" aria-hidden="true">01</span><p><b>{c['buy1']}</b><span>{c['buy1text']}</span></p></div><div><span class="small-icon" aria-hidden="true">02</span><p><b>{c['buy2']}</b><span>{c['buy2text']}</span></p></div><div><span class="small-icon" aria-hidden="true">03</span><p><b>{c['buy3']}</b><span>{c['buy3text']}</span></p></div></div></section>
<section id="how" class="how container section"><div class="section-intro"><p class="eyebrow">{c['howkicker']}</p><h2>{c['howtitle']}</h2><p class="section-lead">{c['howlead']}</p></div><div class="ways"><article class="way sip"><span class="way-tag">01 / SIP</span><svg class="way-icon" viewBox="0 0 120 120" aria-hidden="true"><path d="M45 91h35l5-53H40l5 53Zm16-53V16h26M35 38h55M51 54h20M53 67h16"/></svg><h3>{c['siptitle']}</h3><p>{c['siptext']}</p></article><article class="way swig"><span class="way-tag">02 / SWIG</span><svg class="way-icon" viewBox="0 0 120 120" aria-hidden="true"><path d="m36 74 38-38 25 25-38 38-25-25ZM67 43l-9-9 12-12 9 9M41 69l25 25M27 34c0 10-14 10-14 0 0-5 7-13 7-13s7 8 7 13Z"/></svg><h3>{c['swigtitle']}</h3><p>{c['swigtext']}</p></article></div></section>
<section class="details-section"><div class="container section details-grid"><div class="details-heading"><p class="eyebrow">{c['featureskicker']}</p><h2>{c['featurestitle']}</h2><div class="detail-art" aria-hidden="true"><span>32<small>oz</small></span><svg viewBox="0 0 100 100"><path d="M42 9h16v12l8 8v53a10 10 0 0 1-10 10H44a10 10 0 0 1-10-10V29l8-8V9Zm-8 28h32M42 21h16"/></svg></div></div><ul class="feature-list">{features}</ul></div></section>
<section class="container fit section"><div><p class="eyebrow">{c['fitkicker']}</p><h2>{c['fittitle']}</h2><p class="section-lead">{c['fittext']}</p></div><p class="fit-note">{c['fitnote']}</p></section>
<section class="final-cta"><div class="container final-inner"><div><p class="eyebrow">{c['finalkicker']}</p><h2>{c['finaltitle']}</h2><p>{c['finaltext']}</p></div><div class="final-action">{cta('closing')}<p>{c['affiliate']}</p></div></div></section>
<section class="container faq section" id="questions"><h2>{c['faqtitle']}</h2><div class="faq-list">{faqs}</div></section>
</main>
<footer class="footer"><div class="container"><div class="footer-top"><a class="brand" href="{c['path']}"><span>LUMEN<small>STORE</small></span></a><a href="/catalogo.html">{c['catalog']}</a></div><p class="footer-statement">{statement}</p><p class="footer-legal">{c['footer']}</p><details class="privacy" id="privacy"><summary>{c['privacy']}</summary><p>{c['privacytext']}</p><button type="button" data-opt-out data-disabled-text="{c['disabled']}">{c['optout']}</button></details><div class="footer-bottom"><span>© 2026 LUMEN STORE</span><a href="https://owalalife.com/products/freesip" target="_blank" rel="noopener">{c['source']} ↗</a></div></div></footer>
<div class="mobile-buy"><div><strong>Owala FreeSip</strong><span>32 oz · Denim</span></div>{cta('mobile_bar', True)}</div>
</body></html>'''

for language in COPY:
    target = ROOT / ('en/index.html' if language == 'en' else 'index.html')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build(language), encoding='utf-8')
print('Built Spanish and English FreeSip landing pages.')
