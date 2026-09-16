-- Backtest jobs and the cached candidate tapes they replay into.
--
-- Applied idempotently at startup by Database.bootstrap_schema(). 'tuning' is
-- allowed now though slice 4 is the first to use it, so the CHECK never has to
-- be dropped and recreated on a live table.
CREATE TABLE IF NOT EXISTS backtest_jobs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_key    TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    status       TEXT        NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued', 'replaying', 'studying', 'tuning', 'done', 'failed', 'cancelled')),
    progress     REAL        NOT NULL DEFAULT 0,
    request      JSONB       NOT NULL,
    report       JSONB,
    error        TEXT
);

CREATE INDEX IF NOT EXISTS backtest_jobs_owner_created
    ON backtest_jobs (owner_key, created_at DESC);

CREATE INDEX IF NOT EXISTS backtest_jobs_queue
    ON backtest_jobs (created_at) WHERE status = 'queued';

-- gzip-compressed JSON rows: [bar_index, [[identity, direction, provisional, confidence, strength], ...]]
CREATE TABLE IF NOT EXISTS signal_tapes (
    key         TEXT        PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    bars        INTEGER     NOT NULL,
    rows        BYTEA       NOT NULL
);
