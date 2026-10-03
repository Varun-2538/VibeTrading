-- Strategy rules and their fire history.
--
-- Applied idempotently at startup by Database.bootstrap_schema(). init-db.sql
-- only runs on an empty volume, so it cannot be the delivery mechanism for a
-- database that already exists.

CREATE TABLE IF NOT EXISTS strategy_rules (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- A browser-minted UUID, not an authenticated identity. It namespaces one
    -- browser's rules; it proves nothing about who is asking.
    owner_key        TEXT NOT NULL,
    owner_kind       TEXT NOT NULL DEFAULT 'anon' CHECK (owner_kind IN ('anon', 'wallet')),
    name             TEXT NOT NULL,
    agent            TEXT NOT NULL CHECK (agent IN ('pattern', 'liquidity')),
    symbol           TEXT NOT NULL,
    timeframe        TEXT NOT NULL,
    params           JSONB NOT NULL,
    action           JSONB NOT NULL DEFAULT '{"kind": "alert"}'::jsonb,
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    cooldown_secs    INTEGER NOT NULL DEFAULT 900 CHECK (cooldown_secs >= 0),
    persist_bars     SMALLINT NOT NULL DEFAULT 1 CHECK (persist_bars BETWEEN 0 AND 5),
    -- The candidate signal seen at the previous closed bar, held so a signal
    -- must survive persist_bars closes before it fires.
    pending          JSONB,
    last_candle_time TIMESTAMPTZ,
    last_fired_at    TIMESTAMPTZ,
    fire_count       INTEGER NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rules_owner
    ON strategy_rules (owner_key, created_at DESC);

-- The sweep reads only armed rules, so keep the index that narrow.
CREATE INDEX IF NOT EXISTS idx_rules_armed
    ON strategy_rules (symbol, timeframe) WHERE enabled;

CREATE TABLE IF NOT EXISTS strategy_rule_events (
    id            BIGSERIAL PRIMARY KEY,
    rule_id       UUID NOT NULL REFERENCES strategy_rules(id) ON DELETE CASCADE,
    -- Denormalised so the owner's feed never joins back to strategy_rules.
    owner_key     TEXT NOT NULL,
    -- This UNIQUE constraint is the idempotency guarantee: a repeated sweep
    -- over the same closed bar conflicts instead of firing twice.
    dedup_key     TEXT NOT NULL UNIQUE,
    symbol        TEXT NOT NULL,
    timeframe     TEXT NOT NULL,
    agent         TEXT NOT NULL,
    direction     TEXT CHECK (direction IN ('bullish', 'bearish', 'neutral')),
    price         NUMERIC(20, 8) NOT NULL,
    candle_time   TIMESTAMPTZ NOT NULL,
    fired_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- True when the signal came from a forming/approaching state, which can
    -- still repaint. Never allowed to drive anything but an alert.
    provisional   BOOLEAN NOT NULL DEFAULT FALSE,
    evidence      JSONB NOT NULL,
    action_kind   TEXT NOT NULL DEFAULT 'alert',
    action_status TEXT NOT NULL DEFAULT 'pending',
    action_result JSONB
);

CREATE INDEX IF NOT EXISTS idx_events_owner
    ON strategy_rule_events (owner_key, fired_at DESC);

CREATE INDEX IF NOT EXISTS idx_events_rule
    ON strategy_rule_events (rule_id, fired_at DESC);
