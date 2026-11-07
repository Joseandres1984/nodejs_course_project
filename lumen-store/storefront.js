"use strict";
(() => {
  const products = JSON.parse(document.getElementById("catalog-data").textContent);
  const byId = new Map(products.map(product => [product.asin, product]));
  const root = document.getElementById("products");
  const search = document.getElementById("search");
  const dialog = document.getElementById("product-dialog");
  const storageKey = "lumen-store:favorites:v1";
  let category = "Todos";
  let savedOnly = false;
  let toastTimer;
  let currentProduct = null;
  let lastDialogTrigger = null;
  let storageAvailable = true;
  const saved = new Set();
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey) || "[]");
    if (Array.isArray(stored)) stored.filter(id => byId.has(id)).forEach(id => saved.add(id));
  } catch { storageAvailable = false; }

  const escape = value => String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  const normalize = value => String(value).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("es").trim();
  const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const amazonUrl = product => `https://www.amazon.com/dp/${encodeURIComponent(product.asin)}?tag=lumenb2b-20`;
  const behavior = () => matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth";
  const goToCatalog = () => document.getElementById("catalogo").scrollIntoView({behavior: behavior()});

  function announce(message) {
    const toast = document.getElementById("toast");
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.add("visible");
    toastTimer = setTimeout(() => toast.classList.remove("visible"), 2600);
  }

  function updateSavedControls() {
    document.querySelectorAll("[data-favorite-count]").forEach(node => { node.textContent = saved.size; });
    document.querySelectorAll("[data-save]").forEach(button => {
      const isSaved = saved.has(button.dataset.save);
      const name = byId.get(button.dataset.save)?.displayName || "producto";
      button.setAttribute("aria-pressed", String(isSaved));
      button.setAttribute("aria-label", `${isSaved ? "Quitar de favoritos" : "Guardar en favoritos"}: ${name}`);
      const text = button.querySelector("[data-save-text]");
      if (text) text.textContent = isSaved ? "Guardado en tus favoritos" : "Guardar para después";
    });
    const headerButton = document.querySelector(".header-action[data-show-saved]");
    headerButton.setAttribute("aria-label", `Ver favoritos: ${saved.size} ${saved.size === 1 ? "producto" : "productos"}`);
  }

  function toggleSaved(id) {
    if (!byId.has(id)) return;
    const wasSaved = saved.has(id);
    wasSaved ? saved.delete(id) : saved.add(id);
    try { localStorage.setItem(storageKey, JSON.stringify([...saved])); storageAvailable = true; }
    catch { storageAvailable = false; }
    if (savedOnly) render(); else updateSavedControls();
    announce(wasSaved ? "Producto quitado de tus favoritos" : storageAvailable ? "Guardado. Volvé a verlo en Favoritos ♥" : "Guardado durante esta visita. Este navegador no permite conservarlo.");
  }

  function card(product, index) {
    const p = product;
    const isSaved = saved.has(p.asin);
    return `<article class="product-card" data-product="${p.asin}">
      <div class="product-visual">
        <button class="product-image-button" type="button" data-detail="${p.asin}" aria-label="Ver detalle de ${escape(p.displayName)}"><img src="${escape(p.art)}" width="360" height="400" alt="Imagen ilustrativa de ${escape(p.displayName)}" loading="${index < 4 ? "eager" : "lazy"}" decoding="async"></button>
        <span class="product-tag">${escape(p.label)}</span>
        <button class="save-button" type="button" data-save="${p.asin}" aria-pressed="${isSaved}" aria-label="${isSaved ? "Quitar de favoritos" : "Guardar en favoritos"}: ${escape(p.displayName)}">${icon("heart")}</button>
        <button class="quick-view" type="button" data-detail="${p.asin}">Vista rápida</button>
      </div>
      <div class="product-info"><span class="product-collection">${escape(p.collection)}</span><h3 class="product-title"><button class="title-button" type="button" data-detail="${p.asin}">${escape(p.displayName)}</button></h3><p class="product-feature">${escape(p.feature)}</p><div class="product-footer"><p class="price-note">${icon("external")} Precio actual en Amazon</p><a class="amazon-link" href="${amazonUrl(p)}" target="_blank" rel="sponsored nofollow noopener" aria-label="Ver ${escape(p.displayName)} en Amazon (abre otra pestaña)">Ver en Amazon ${icon("external")}</a></div></div>
    </article>`;
  }

  function render() {
    const words = normalize(search.value).split(/\s+/).filter(Boolean);
    let shown = products.filter(p => (category === "Todos" || p.collection === category) && (!savedOnly || saved.has(p.asin)) && words.every(word => normalize([p.name, p.displayName, p.collection, p.category, p.feature, p.description, p.asin].join(" ")).includes(word)));
    const sort = document.getElementById("sort").value;
    if (sort === "az" || sort === "za") shown.sort((a,b) => a.displayName.localeCompare(b.displayName, "es") * (sort === "za" ? -1 : 1));
    const title = document.getElementById("catalog-title");
    const description = document.getElementById("catalog-description");
    title.textContent = savedOnly ? "Tus favoritos, todos juntos." : category !== "Todos" ? `${category}: encontrá tu favorito.` : "Tu próximo favorito está acá.";
    description.textContent = savedOnly ? "Esos hallazgos a los que querés volver." : category !== "Todos" ? "Pequeños detalles para disfrutar todos los días." : "Ideas para vos, para tu casa y para regalar.";
    const count = document.getElementById("result-count");
    count.textContent = `${shown.length} ${shown.length === 1 ? "producto" : "productos"}${savedOnly ? " en tus favoritos" : " para descubrir"}${search.value.trim() ? ` · “${search.value.trim()}”` : ""}`;
    document.getElementById("clear-filter").hidden = category === "Todos" && !savedOnly && !search.value;
    if (shown.length) root.innerHTML = shown.map(card).join("");
    else {
      const emptySaved = savedOnly && saved.size === 0;
      root.innerHTML = `<div class="empty-state">${icon(emptySaved ? "heart" : "search")}<h3>${emptySaved ? "Tu próximo favorito te está esperando." : "Todavía no encontramos ese hallazgo."}</h3><p>${emptySaved ? "Tocá el corazón de un producto para guardarlo acá." : "Probá con otro nombre o explorá toda la selección."}</p><button type="button" data-reset>Descubrir productos ${icon("arrow")}</button></div>`;
    }
    document.querySelectorAll("[data-category]").forEach(button => {
      const active = !savedOnly && button.dataset.category === category;
      if (button.classList.contains("filter") || button.classList.contains("nav-category")) {
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", String(active));
      }
    });
    document.querySelectorAll("[data-show-saved]").forEach(button => {
      button.classList.toggle("active", savedOnly);
      button.setAttribute("aria-pressed", String(savedOnly));
    });
    updateSavedControls();
  }

  function reset() {
    category = "Todos"; savedOnly = false; search.value = "";
    document.getElementById("sort").value = "selected";
    render();
  }

  function setCategory(value) {
    category = value; savedOnly = false; search.value = "";
    render(); goToCatalog();
  }

  function openProduct(id, trigger) {
    const p = byId.get(id);
    if (!p) return;
    currentProduct = p;
    lastDialogTrigger = trigger;
    document.getElementById("dialog-body").innerHTML = `<div class="dialog-grid"><div class="dialog-image"><img src="${escape(p.art)}" alt="Imagen ilustrativa de ${escape(p.displayName)}" width="400" height="440"></div><div class="dialog-content"><span class="eyebrow gold">${escape(p.collection)} · Selección LUMEN</span><h2 id="dialog-title">${escape(p.displayName)}</h2><p class="dialog-benefit">${escape(p.benefit)}</p><p class="description">${escape(p.description)}</p><a class="amazon-link" href="${amazonUrl(p)}" target="_blank" rel="sponsored nofollow noopener" aria-label="Ver ${escape(p.displayName)} en Amazon (abre otra pestaña)">Ver precio en Amazon ${icon("external")}</a><button class="dialog-save" type="button" data-save="${p.asin}" aria-pressed="${saved.has(p.asin)}">${icon("heart")}<span data-save-text>Guardar para después</span></button><p class="dialog-disclaimer">Imagen ilustrativa. Revisá el producto exacto, sus variantes, la disponibilidad y el envío en Amazon. Enlace de afiliado.</p></div></div>`;
    updateSavedControls();
    dialog.showModal();
    document.body.style.overflow = "hidden";
  }

  function closeProduct() { dialog.close(); }
  dialog.addEventListener("close", () => {
    document.body.style.overflow = "";
    const id = currentProduct?.asin;
    currentProduct = null;
    if (lastDialogTrigger?.isConnected) lastDialogTrigger.focus({preventScroll:true});
    else if (id) document.querySelector(`[data-detail="${id}"]`)?.focus({preventScroll:true});
  });
  dialog.querySelector(".dialog-close").addEventListener("click", closeProduct);
  dialog.addEventListener("click", event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeProduct();
  });

  document.addEventListener("click", event => {
    const target = event.target.closest("[data-category], [data-show-saved], [data-save], [data-detail], [data-reset], [data-explore], [data-home]");
    if (!target) return;
    if (target.hasAttribute("data-save")) { toggleSaved(target.dataset.save); return; }
    if (target.hasAttribute("data-detail")) { openProduct(target.dataset.detail, target); return; }
    if (target.hasAttribute("data-show-saved")) { savedOnly = true; category = "Todos"; search.value = ""; render(); goToCatalog(); return; }
    if (target.hasAttribute("data-category")) { setCategory(target.dataset.category); return; }
    if (target.hasAttribute("data-reset")) { reset(); goToCatalog(); return; }
    if (target.hasAttribute("data-explore")) reset();
    if (target.hasAttribute("data-home")) reset();
  });
  document.getElementById("search-form").addEventListener("submit", event => {
    event.preventDefault(); render(); search.blur(); goToCatalog();
  });
  search.addEventListener("input", render);
  document.getElementById("sort").addEventListener("change", render);
  document.getElementById("clear-filter").addEventListener("click", () => {reset();goToCatalog();});
  window.addEventListener("storage", event => {
    if (event.key !== storageKey && event.key !== null) return;
    try {
      const stored = JSON.parse(localStorage.getItem(storageKey) || "[]");
      saved.clear();
      if (Array.isArray(stored)) stored.filter(id => byId.has(id)).forEach(id => saved.add(id));
      render();
    } catch { /* Keep this visit's selection when browser storage is unavailable. */ }
  });
  document.getElementById("year").textContent = new Date().getFullYear();
  render();
})();
