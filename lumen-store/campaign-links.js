"use strict";
(() => {
  // Keep only attribution values explicitly supplied by the campaign.
  // No cookies, tracking pixels, personal data, or third-party requests.
  const params = new URLSearchParams(window.location.search);
  const keys = ["utm_source", "utm_medium", "utm_campaign", "utm_content"];
  const campaign = new URLSearchParams();
  for (const key of keys) {
    const value = params.get(key);
    if (value && /^[A-Za-z0-9_-]{1,80}$/.test(value)) campaign.set(key, value);
  }
  if (params.get("lumen_qa") === "1") campaign.set("lumen_qa", "1");
  if (!campaign.size) return;
  document.querySelectorAll('a[href]').forEach(link => {
    const raw = link.getAttribute("href") || "";
    if (!raw || raw.startsWith("#") || raw.startsWith("mailto:") || raw.startsWith("tel:")) return;
    let url;
    try { url = new URL(raw, window.location.href); } catch { return; }
    if (url.origin !== window.location.origin) return;
    if (url.pathname === window.location.pathname && url.hash) return;
    campaign.forEach((value, key) => {
      if (!url.searchParams.has(key)) url.searchParams.set(key, value);
    });
    link.href = url.href;
  });
})();
