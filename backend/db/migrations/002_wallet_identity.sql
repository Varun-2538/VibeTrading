-- Rules belong to a wallet address that proved itself, not to a browser.
--
-- Applied idempotently at startup by Database.bootstrap_schema(), which runs
-- every migration on every boot - so everything here has to survive being run
-- again. It does: once anonymous rules cannot be created, the DELETE matches
-- nothing and the ALTER sets a default that is already set.

-- The anonymous owner_key was an unverified browser UUID: anyone who sent
-- someone else's key held their rules. There is no way to establish which wallet
-- an anonymous rule belonged to, so they go rather than get migrated.
-- strategy_rule_events cascades on the foreign key.
DELETE FROM strategy_rules WHERE owner_kind = 'anon';

ALTER TABLE strategy_rules ALTER COLUMN owner_kind SET DEFAULT 'wallet';

COMMENT ON COLUMN strategy_rules.owner_key IS
    'Lowercased wallet address, proven by an EIP-4361 signature at sign-in. '
    'Lowercased because EIP-55 checksumming varies the case of one address, and '
    'two casings must not become two owners.';
