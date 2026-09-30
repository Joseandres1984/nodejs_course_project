CREATE TABLE IF NOT EXISTS lumen_viator_payout_settings (
  id TEXT PRIMARY KEY CHECK(id='primary'),
  configured INTEGER NOT NULL DEFAULT 0,
  method TEXT NOT NULL DEFAULT 'UNKNOWN',
  currency TEXT,
  confirmed_by_user INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO lumen_viator_payout_settings(
  id, configured, method, currency, confirmed_by_user, updated_at
) VALUES(
  'primary', 0, 'UNKNOWN', NULL, 0, datetime('now')
);

UPDATE lumen_viator_payout_settings
SET configured = 1,
    method = 'PAYPAL',
    confirmed_by_user = 1,
    updated_at = datetime('now')
WHERE id = 'primary'
  AND configured = 0
  AND method = 'UNKNOWN'
  AND confirmed_by_user = 0;
