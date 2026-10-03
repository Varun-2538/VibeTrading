-- A third rule type: ordered candle/indicator sequences.
--
-- Applied idempotently at startup by Database.bootstrap_schema(). Postgres has
-- no ADD CONSTRAINT IF NOT EXISTS, so the constraint is dropped and recreated
-- under a fixed name; on a second run that is a no-op with a different route.
ALTER TABLE strategy_rules DROP CONSTRAINT IF EXISTS strategy_rules_agent_check;
ALTER TABLE strategy_rules
    ADD CONSTRAINT strategy_rules_agent_check
    CHECK (agent IN ('pattern', 'liquidity', 'sequence'));
