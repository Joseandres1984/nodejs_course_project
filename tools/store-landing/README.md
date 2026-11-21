# LUMEN Store: focused FreeSip campaign

Production: https://lumen-store-6ahq.onrender.com/

English: https://lumen-store-6ahq.onrender.com/en/

The previous nine-product storefront remains at `/catalogo.html`. The homepage now presents one specific product, Owala FreeSip stainless steel 32 oz Denim, ASIN `B0BZYBSRNF`, using the existing affiliate tracking ID `lumenb2b-20`.

## Rebuild

```sh
python tools/store-landing/build-pages.py
npm ci --prefix tools/store-landing
node tools/store-landing/build-analytics.mjs
```

Supply `LUMEN_POSTHOG_TOKEN` and `LUMEN_POSTHOG_HOST` through the build environment or the untracked `tools/store-landing/.env.local`. Only the public project token is compiled into the deployed browser bundle. The existing Render static service publishes `lumen-store` without a build step, so generated HTML and JS are tracked as deployment assets alongside their build sources. Never add a personal API key to browser code.

## Measurement contract

- `lumen_landing_view`: a loaded product landing page.
- `lumen_catalog_view`: a loaded catalog page.
- `lumen_affiliate_click`: a deliberate left click or keyboard activation on a direct Amazon product link bearing the existing affiliate tag. Properties include ASIN, language, CTA placement and allowlisted campaign fields.
- `lumen_language_switch`: selection of the other page language.
- `lumen_ui_error`: an unhandled script error count, without message or stack.
- `?lumen_qa=1` prefixes every event with `lumen_qa_` and sets `is_qa=true`. Exclude these events from campaign results. Preview traffic is otherwise ignored.

Analytics cannot observe an Amazon purchase or confirm a commission. Reconcile orders and confirmed commissions with official Amazon Associates reports. A click is never a sale event. No revenue event is emitted by this site.

The SDK uses memory-only identity, no person profiles, no session recording, no autocapture, no IP-based geolocation, and respects DNT/GPC. URL and referrer properties are removed; campaign values must match a short, restricted character set. A visitor can disable measurement. Analytics failure does not prevent any shopping link from working.

## Launch and commercial target

Use the Spanish or English URL matching the Instagram post. Campaign URL example: `/?utm_source=instagram&utm_medium=organic&utm_campaign=owala_freesip_32&utm_content=sip_swig_es`. Keep paid spend disabled until confirmed commissions per visit support a profitable acquisition cost.

The working goal is USD 5,000 in affiliate commissions. It is a target without an assigned deadline, not recorded income or a forecast. Hypothetical required completed purchases: 3,334 at USD 1.50 average net commission, 1,000 at USD 5, or 500 at USD 10. Actual commission rates, order value, cancellations and returns must come from Amazon reports.

No discount, inventory count, deadline, product rating or customer testimonial is fabricated. Until an authorized pricing feed is available, all current prices and promotions are checked on Amazon.

## Verified product references

- Manufacturer features and care: https://owalalife.com/products/freesip
- Linked model: https://www.amazon.com/dp/B0BZYBSRNF (title checked against the existing Denim product photo).
- Affiliate prices and promotions: https://affiliate-program.amazon.com/help/operating/policies
- Required disclosure: https://affiliate-program.amazon.com/help/node/topic/GHQNZAU6669EZS98

Feature claims were checked on November 4, 2026. Amazon price, availability, delivery and commission were not certified. Product selection is the first campaign hypothesis and has not been declared a sales winner.
