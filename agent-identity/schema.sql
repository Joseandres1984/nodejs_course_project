-- LUMEN Agent Identity v1: experimental did:agent:ed25519 DID method.
-- Apply to an isolated D1 database, NEVER to the existing LUMEN production database.
CREATE TABLE IF NOT EXISTS agent_identities (
    did TEXT PRIMARY KEY,
    controller_did TEXT NOT NULL,
    public_key TEXT NOT NULL,
    key_type TEXT NOT NULL DEFAULT 'ed25519' CHECK (key_type = 'ed25519'),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','revoked')),
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS protocol_registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    did TEXT NOT NULL REFERENCES agent_identities(did),
    protocol TEXT NOT NULL CHECK (protocol IN ('a2a','mcp','ucp','x402')),
    protocol_id TEXT NOT NULL,
    registration_data TEXT,
    verified INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0,1)),
    verified_at INTEGER,
    created_at INTEGER NOT NULL,
    UNIQUE(did, protocol)
);
CREATE TABLE IF NOT EXISTS credentials (
    id TEXT PRIMARY KEY,
    did TEXT NOT NULL REFERENCES agent_identities(did),
    issuer_did TEXT NOT NULL,
    type TEXT NOT NULL,
    claims TEXT NOT NULL,
    signature TEXT NOT NULL,
    issued_at INTEGER NOT NULL,
    expires_at INTEGER,
    revoked INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0,1)),
    revoked_at INTEGER
);
CREATE TABLE IF NOT EXISTS reputation_events (
    id TEXT PRIMARY KEY,
    did TEXT NOT NULL REFERENCES agent_identities(did),
    protocol TEXT NOT NULL CHECK (protocol IN ('a2a','mcp','ucp','x402')),
    event_type TEXT NOT NULL CHECK (event_type IN ('positive','negative','neutral')),
    weight REAL NOT NULL CHECK (weight > 0 AND weight <= 1),
    description TEXT,
    metadata TEXT,
    source_did TEXT NOT NULL REFERENCES agent_identities(did),
    signature TEXT NOT NULL,
    timestamp INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reputation_scores (
    did TEXT PRIMARY KEY REFERENCES agent_identities(did),
    global_score REAL NOT NULL DEFAULT 50,
    protocol_scores TEXT NOT NULL DEFAULT '{}',
    category_scores TEXT NOT NULL DEFAULT '{}',
    total_interactions INTEGER NOT NULL DEFAULT 0,
    success_rate REAL NOT NULL DEFAULT 0,
    last_computed INTEGER NOT NULL,
    decay_factor REAL NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS identity_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    primary_did TEXT NOT NULL REFERENCES agent_identities(did),
    linked_did TEXT NOT NULL REFERENCES agent_identities(did),
    link_type TEXT NOT NULL CHECK (link_type IN ('alias','delegation','ownership')),
    proof TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER,
    UNIQUE(primary_did,linked_did,link_type)
);
CREATE TABLE IF NOT EXISTS request_nonces (
    did TEXT NOT NULL,
    nonce TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    PRIMARY KEY(did,nonce)
);
CREATE INDEX IF NOT EXISTS idx_identities_status ON agent_identities(status);
CREATE INDEX IF NOT EXISTS idx_credentials_did ON credentials(did);
CREATE INDEX IF NOT EXISTS idx_reputation_did_time ON reputation_events(did,timestamp);
CREATE INDEX IF NOT EXISTS idx_reputation_source ON reputation_events(source_did);
CREATE INDEX IF NOT EXISTS idx_links_primary ON identity_links(primary_did);
CREATE INDEX IF NOT EXISTS idx_links_linked ON identity_links(linked_did);
CREATE INDEX IF NOT EXISTS idx_nonces_expiry ON request_nonces(expires_at);
