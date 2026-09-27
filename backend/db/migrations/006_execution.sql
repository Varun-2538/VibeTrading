-- The execution layer: what may trade, what was decided, and what was sent.
--
-- Applied idempotently at startup by Database.bootstrap_schema(), from more than
-- one process, so every statement is IF NOT EXISTS-safe. Postgres has no
-- ADD CONSTRAINT IF NOT EXISTS; where a constraint has to change later it is
-- dropped and re-added under a fixed name, as 003 does.
--
-- Nothing here executes anything. The global switch ships off, every account
-- ships off, and the tables past execution_policies have no writer until the
-- executor exists. They are created now so the constraints that make
-- double-spending impossible are in place before the code that could.
--
-- Tables are ordered so every REFERENCES points backwards. The one cycle - a
-- position names the intent that opened it, an exit intent names its position -
-- is broken on the position side: entry_intent_id carries no foreign key,
-- deliberately, because a mid-file circular constraint cannot be written
-- idempotently.

-- One row, so the brake can be read in the same statement that claims work and
-- released with one UPDATE. Off by default: deploying this must arm nothing.
CREATE TABLE IF NOT EXISTS execution_settings (
    id            SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    enabled       BOOLEAN     NOT NULL DEFAULT FALSE,
    halted_reason TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO execution_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Per wallet. There is no users table, so owner_key - the lowercased address
-- auth_service proved at sign-in - is the primary key. Every cap defaults to the
-- most restrictive useful value, and mode defaults to 'off'.
CREATE TABLE IF NOT EXISTS execution_accounts (
    owner_key                TEXT PRIMARY KEY,
    mode                     TEXT NOT NULL DEFAULT 'off'
                             CHECK (mode IN ('off', 'shadow', 'live')),
    kill_switch              BOOLEAN NOT NULL DEFAULT FALSE,
    -- What the sizing maths treats as the account, declared by the owner until a
    -- vault can report its own balance. Only ever shrinks a position.
    equity_usd               NUMERIC(20, 8) NOT NULL DEFAULT 0 CHECK (equity_usd >= 0),
    max_notional_usd         NUMERIC(20, 8) NOT NULL DEFAULT 100 CHECK (max_notional_usd > 0),
    max_concurrent_positions SMALLINT NOT NULL DEFAULT 1 CHECK (max_concurrent_positions BETWEEN 0 AND 20),
    max_trades_per_day       SMALLINT NOT NULL DEFAULT 5 CHECK (max_trades_per_day BETWEEN 0 AND 200),
    daily_loss_limit_usd     NUMERIC(20, 8) NOT NULL DEFAULT 25 CHECK (daily_loss_limit_usd > 0),
    -- Set by reconciliation when it finds something it cannot explain, cleared
    -- only by a person. An account halted this way keeps closing positions and
    -- stops opening them.
    halted_reason            TEXT,
    halted_at                TIMESTAMPTZ,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- A backtest can now say which rule it was run for, so the arming gate finds a
-- rule's evidence by id instead of comparing JSON blobs and hoping key order is
-- stable.
ALTER TABLE backtest_jobs ADD COLUMN IF NOT EXISTS rule_id UUID;
CREATE INDEX IF NOT EXISTS backtest_jobs_rule
    ON backtest_jobs (rule_id, created_at DESC) WHERE status = 'done';

-- The armed copy of a rule's execution config, and the evidence that armed it.
-- Separate from strategy_rules.action on purpose: action is what the owner
-- declared, this is what the server agreed to, so an ordinary PATCH of the rule
-- can revoke the agreement without being able to forge one.
CREATE TABLE IF NOT EXISTS execution_policies (
    rule_id         UUID PRIMARY KEY REFERENCES strategy_rules(id) ON DELETE CASCADE,
    owner_key       TEXT    NOT NULL,
    armed           BOOLEAN NOT NULL DEFAULT FALSE,
    venue           TEXT    NOT NULL,
    market          TEXT    NOT NULL,
    -- An ExitPlan, dumped verbatim: the same model the backtester validates.
    exit_plan       JSONB   NOT NULL,
    -- The rest of the action config - neutral, sides, delays, slippage, caps.
    policy          JSONB   NOT NULL,
    -- services.trade_plan.PARITY_VERSION when this was armed. A rule armed under
    -- older exit semantics is refused rather than migrated.
    parity_version  INTEGER NOT NULL,
    backtest_job_id UUID REFERENCES backtest_jobs(id) ON DELETE SET NULL,
    preflight       JSONB,
    armed_at        TIMESTAMPTZ,
    disarmed_reason TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS execution_policies_armed
    ON execution_policies (owner_key) WHERE armed;

CREATE TABLE IF NOT EXISTS execution_positions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_key         TEXT NOT NULL,
    rule_id           UUID NOT NULL REFERENCES strategy_rules(id) ON DELETE CASCADE,
    venue             TEXT NOT NULL,
    market            TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    timeframe         TEXT NOT NULL,
    direction         SMALLINT NOT NULL CHECK (direction IN (-1, 1)),
    status            TEXT NOT NULL DEFAULT 'opening'
                      CHECK (status IN ('opening', 'open', 'closing', 'closed', 'abandoned')),
    mode              TEXT NOT NULL CHECK (mode IN ('shadow', 'live')),
    -- No foreign key: see the note at the top of this file.
    entry_intent_id   UUID NOT NULL,
    entry_event_id    BIGINT,
    -- The plan this position is managed under, snapshotted at entry. Editing the
    -- rule afterwards must not be able to move a live stop.
    plan              JSONB NOT NULL,
    parity_version    INTEGER NOT NULL,
    signal_bar_time   TIMESTAMPTZ NOT NULL,
    entry_bar_time    TIMESTAMPTZ,
    entry_price       NUMERIC(20, 8),
    qty               NUMERIC(38, 18),
    notional_usd      NUMERIC(20, 8),
    stop_price        NUMERIC(20, 8) NOT NULL,
    target_price      NUMERIC(20, 8),
    -- The open time of the bar at which max_bars expires. A clock time rather
    -- than a bar count, so the time exit needs no market data at all - which is
    -- what makes it the exit that still works when candles are unavailable.
    deadline_bar_time TIMESTAMPTZ NOT NULL,
    triggers_placed   BOOLEAN NOT NULL DEFAULT FALSE,
    exit_price        NUMERIC(20, 8),
    exit_reason       TEXT CHECK (exit_reason IN
                      ('stop', 'target', 'time', 'opposite', 'flatten', 'reconciled', 'end')),
    closed_at         TIMESTAMPTZ,
    realised_pnl_usd  NUMERIC(20, 8),
    realised_r        NUMERIC(20, 8),
    -- What the backtester would have used and what was actually got, with the
    -- drift in basis points. This is how a report and a fill are compared.
    reference         JSONB,
    reconciled_at     TIMESTAMPTZ,
    opened_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- THE double-spend guard, and the reason two executors running at once cannot
-- double a position: the second INSERT conflicts here instead of succeeding.
-- backtest/trades.py holds one position at a time, so this is also what keeps
-- live faithful to the simulation.
CREATE UNIQUE INDEX IF NOT EXISTS execution_positions_one_live
    ON execution_positions (owner_key, rule_id, venue, market, mode)
    WHERE status IN ('opening', 'open', 'closing');

CREATE INDEX IF NOT EXISTS execution_positions_live
    ON execution_positions (deadline_bar_time)
    WHERE status IN ('opening', 'open', 'closing');
CREATE INDEX IF NOT EXISTS execution_positions_owner
    ON execution_positions (owner_key, opened_at DESC);

CREATE TABLE IF NOT EXISTS execution_intents (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_key      TEXT NOT NULL,
    rule_id        UUID NOT NULL REFERENCES strategy_rules(id) ON DELETE CASCADE,
    -- The fire this came from, whose dedup_key already made it idempotent. NULL
    -- for exits, which are not fires.
    event_id       BIGINT REFERENCES strategy_rule_events(id) ON DELETE SET NULL,
    position_id    UUID REFERENCES execution_positions(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL CHECK (kind IN
                   ('entry', 'exit_stop', 'exit_target', 'exit_time',
                    'exit_opposite', 'flatten')),
    status         TEXT NOT NULL DEFAULT 'queued' CHECK (status IN
                   ('queued', 'claimed', 'submitting', 'filled', 'rejected',
                    'expired', 'cancelled', 'failed', 'needs_reconcile')),
    mode           TEXT NOT NULL CHECK (mode IN ('shadow', 'live')),
    venue          TEXT NOT NULL,
    market         TEXT NOT NULL,
    side           TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    -- Snapshots. The executor never re-reads the rule or the policy, so editing
    -- either cannot retarget work already in flight.
    plan           JSONB NOT NULL,
    reference      JSONB NOT NULL,
    sizing         JSONB,
    parity_version INTEGER NOT NULL,
    -- Past this an entry is abandoned rather than chased: a fill forty minutes
    -- after the bar it was priced from is a different trade.
    not_after      TIMESTAMPTZ NOT NULL,
    attempts       SMALLINT NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    claimed_at     TIMESTAMPTZ,
    claimed_by     TEXT,
    finished_at    TIMESTAMPTZ,
    error          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- At most one intent per fire, ever. This is what makes "turn queued events into
-- intents" safe to re-run, and what stops a second sweep from double-queueing.
CREATE UNIQUE INDEX IF NOT EXISTS execution_intents_one_per_event
    ON execution_intents (event_id) WHERE event_id IS NOT NULL;

-- At most one exit of each kind per position. Without this a monitor tick that
-- runs twice across a restart queues two flattens, and the second one opens a
-- reverse position.
CREATE UNIQUE INDEX IF NOT EXISTS execution_intents_one_exit_per_position
    ON execution_intents (position_id, kind)
    WHERE position_id IS NOT NULL AND kind <> 'entry';

CREATE INDEX IF NOT EXISTS execution_intents_queue
    ON execution_intents (created_at) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS execution_intents_owner
    ON execution_intents (owner_key, created_at DESC);

-- Insert-only. A row exists before the venue is called and is never deleted, so
-- "the process died inside the swap" is a readable state rather than a gap.
CREATE TABLE IF NOT EXISTS execution_orders (
    id              BIGSERIAL PRIMARY KEY,
    owner_key       TEXT NOT NULL,
    intent_id       UUID NOT NULL REFERENCES execution_intents(id) ON DELETE CASCADE,
    position_id     UUID,
    -- THE idempotency key for one venue write: derived only from durable facts,
    -- so a retry regenerates it byte for byte. The row is inserted before the
    -- call and the same string is handed to the venue, so a duplicate is refused
    -- on both sides of the wire.
    client_order_id TEXT NOT NULL UNIQUE,
    leg             TEXT NOT NULL CHECK (leg IN
                    ('entry', 'stop', 'target', 'exit', 'flatten', 'cancel')),
    kind            TEXT NOT NULL CHECK (kind IN ('market', 'trigger', 'cancel')),
    side            TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    reduce_only     BOOLEAN NOT NULL DEFAULT FALSE,
    qty             NUMERIC(38, 18),
    trigger_price   NUMERIC(20, 8),
    status          TEXT NOT NULL DEFAULT 'submitting' CHECK (status IN
                    ('submitting', 'acked', 'filled', 'partial', 'rejected',
                     'cancelled', 'unknown', 'shadow')),
    venue_order_id  TEXT,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acked_at        TIMESTAMPTZ,
    -- Verbatim, both ways, for a dispute. Never parsed for control flow.
    request         JSONB NOT NULL,
    response        JSONB,
    error           TEXT
);
CREATE INDEX IF NOT EXISTS execution_orders_intent
    ON execution_orders (intent_id, submitted_at);
-- What reconciliation reads first: writes whose outcome was never learned.
CREATE INDEX IF NOT EXISTS execution_orders_in_doubt
    ON execution_orders (submitted_at) WHERE status IN ('submitting', 'unknown');

CREATE TABLE IF NOT EXISTS execution_fills (
    id            BIGSERIAL PRIMARY KEY,
    owner_key     TEXT NOT NULL,
    order_id      BIGINT NOT NULL REFERENCES execution_orders(id) ON DELETE CASCADE,
    position_id   UUID,
    venue         TEXT NOT NULL,
    -- The venue's own id for the trade, so a positions poll replayed after a
    -- restart cannot book the same fill twice.
    venue_fill_id TEXT NOT NULL,
    price         NUMERIC(20, 8) NOT NULL,
    qty           NUMERIC(38, 18) NOT NULL,
    fee_usd       NUMERIC(20, 8) NOT NULL DEFAULT 0,
    gas_usd       NUMERIC(20, 8) NOT NULL DEFAULT 0,
    tx_ref        TEXT,
    filled_at     TIMESTAMPTZ NOT NULL,
    raw           JSONB NOT NULL,
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS execution_fills_venue_unique
    ON execution_fills (venue, venue_fill_id);
CREATE INDEX IF NOT EXISTS execution_fills_position
    ON execution_fills (position_id, filled_at);

-- Every state transition, append-only. This is the row a dispute is answered
-- from, so it records who moved what and why, not only the outcome.
CREATE TABLE IF NOT EXISTS execution_audit (
    id          BIGSERIAL PRIMARY KEY,
    at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    owner_key   TEXT NOT NULL,
    intent_id   UUID,
    position_id UUID,
    order_id    BIGINT,
    actor       TEXT NOT NULL CHECK (actor IN
                ('sweep', 'executor', 'monitor', 'reconcile', 'owner', 'operator')),
    from_status TEXT,
    to_status   TEXT,
    reason      TEXT NOT NULL,
    detail      JSONB
);
CREATE INDEX IF NOT EXISTS execution_audit_owner ON execution_audit (owner_key, at DESC);
CREATE INDEX IF NOT EXISTS execution_audit_position ON execution_audit (position_id, at);
