import posthog from "posthog-js/dist/module.slim.no-external.js";

// Injected by the build from the environment; only the public project token ships.
const token = process.env.LUMEN_POSTHOG_TOKEN;
const apiHost = process.env.LUMEN_POSTHOG_HOST;
const params = new URLSearchParams(location.search);
const isQA = params.get("lumen_qa") === "1";
const siteHost = "lumen-store-6ahq.onrender.com";
const optOutKey = "lumen:measurement:disabled";
let disabled = navigator.doNotTrack === "1" || navigator.globalPrivacyControl === true;
try { disabled ||= localStorage.getItem(optOutKey) === "1"; } catch { /* Optional preference storage. */ }
const campaignValue = name => {
  const value = params.get(name) || "";
  return /^[a-zA-Z0-9_-]{1,80}$/.test(value) ? value : "";
};
const base = {
  lumen_site: siteHost,
  lumen_page: document.body.dataset.page || "catalog",
  asin: document.body.dataset.product || "",
  language: document.body.dataset.language || "es",
  source: campaignValue("utm_source") || "unspecified",
  medium: campaignValue("utm_medium") || "unspecified",
  campaign: campaignValue("utm_campaign") || "unspecified",
  content: campaignValue("utm_content"),
  is_qa: isQA,
  $geoip_disable: true,
};
const allowed = new Set([
  ...Object.keys(base), "placement", "target_language", "error_kind", "distinct_id",
  "token", "$lib", "$lib_version", "$device_id", "$session_id", "$window_id",
  "$ip", "$process_person_profile", "$insert_id", "$time",
]);
let initialized = false;
const capture = (name, properties = {}) => {
  if (disabled || !initialized) return;
  try { posthog.capture(`lumen_${isQA ? "qa_" : ""}${name}`, {...base, ...properties}); }
  catch { /* Analytics must never interfere with shopping. */ }
};
function updateOptOutButtons() {
  document.querySelectorAll("[data-opt-out]").forEach(button => {
    if (disabled) { button.textContent = button.dataset.disabledText; button.disabled = true; }
  });
}
document.querySelectorAll("[data-opt-out]").forEach(button => {
  button.addEventListener("click", () => {
    disabled = true;
    if (initialized) posthog.opt_out_capturing();
    try { localStorage.setItem(optOutKey, "1"); } catch { /* Still disabled for this page. */ }
    updateOptOutButtons();
  });
});
updateOptOutButtons();
if (!disabled && token && apiHost && (location.hostname === siteHost || isQA)) {
  try {
    posthog.init(token, {
      api_host: apiHost,
      persistence: "memory",
      disable_persistence: true,
      opt_out_capturing_persistence_type: "localStorage",
      person_profiles: "never",
      ip: false,
      respect_dnt: true,
      autocapture: false,
      capture_pageview: false,
      capture_pageleave: false,
      capture_exceptions: false,
      capture_dead_clicks: false,
      rageclick: false,
      disable_session_recording: true,
      enable_recording_console_log: false,
      disable_surveys: true,
      advanced_disable_feature_flags: true,
      advanced_disable_decide: true,
      disable_external_dependency_loading: true,
      request_batching: false,
      sanitize_properties: properties => Object.fromEntries(Object.entries(properties).filter(([key]) => allowed.has(key))),
      loaded: () => {
        initialized = true;
        capture(document.body.dataset.page?.startsWith("freesip") ? "landing_view" : "catalog_view");
      },
    });
  } catch { /* A blocked endpoint must not block an affiliate link. */ }
}
document.addEventListener("click", event => {
  const link = event.target.closest?.("a[href]");
  if (!link || event.button !== 0) return;
  if (link.hasAttribute("data-language-switch")) capture("language_switch", {target_language: link.hreflang});
  let url;
  try { url = new URL(link.href); } catch { return; }
  if (url.hostname !== "www.amazon.com" || url.searchParams.get("tag") !== "lumenb2b-20") return;
  const asin = url.pathname.match(/^\/dp\/([A-Z0-9]{10})(?:\/|$)/)?.[1];
  if (!asin) return;
  capture("affiliate_click", {asin, placement: link.dataset.position || "catalog"});
  // Preserve normal anchors, keyboard activation, and shopping when analytics is blocked.
});
document.querySelectorAll("[data-language-switch]").forEach(link => {
  const url = new URL(link.href);
  for (const key of ["utm_source", "utm_medium", "utm_campaign", "utm_content"]) {
    const value = campaignValue(key);
    if (value) url.searchParams.set(key, value);
  }
  if (isQA) url.searchParams.set("lumen_qa", "1");
  link.href = url.href;
});
window.addEventListener("error", event => {
  if (event.target === window) capture("ui_error", {error_kind: "script"});
});
