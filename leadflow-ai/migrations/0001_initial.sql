CREATE TABLE IF NOT EXISTS leads (
  id TEXT PRIMARY KEY NOT NULL,
  created_at TEXT NOT NULL,
  name TEXT NOT NULL,
  email TEXT NOT NULL,
  area TEXT NOT NULL,
  budget_ars INTEGER NOT NULL,
  operation TEXT NOT NULL,
  property_type TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  priority TEXT NOT NULL,
  consent_version TEXT NOT NULL,
  notification_status TEXT NOT NULL DEFAULT 'not_configured'
);
CREATE INDEX IF NOT EXISTS leads_created_desc ON leads(created_at DESC);
CREATE TABLE IF NOT EXISTS rate_limit (
  key TEXT PRIMARY KEY NOT NULL,
  hits INTEGER NOT NULL,
  reset_at INTEGER NOT NULL
);
