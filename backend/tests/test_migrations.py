"""
Migrations run on every boot (Database.bootstrap_schema), so each one must be
safe to apply twice. There is no database in the test run; this checks the
statements that make a re-run a no-op are present.
"""
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations"


def test_candles_history_migration_is_idempotent():
    sql = (MIGRATIONS / "004_candles_history.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS candles_history" in sql
    assert "PRIMARY KEY (symbol, timeframe, time)" in sql
    assert "create_hypertable" in sql
    assert "if_not_exists => TRUE" in sql


def test_migrations_sort_in_application_order():
    names = sorted(p.name for p in MIGRATIONS.glob("*.sql"))
    assert names.index("004_candles_history.sql") == len(
        [n for n in names if n < "004"]
    )


def test_backtests_migration_is_idempotent_and_allows_every_status():
    sql = (MIGRATIONS / "005_backtests.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS backtest_jobs" in sql
    assert "CREATE TABLE IF NOT EXISTS signal_tapes" in sql
    assert sql.count("CREATE INDEX IF NOT EXISTS") == 2
    for status in ("queued", "replaying", "studying", "tuning", "done", "failed", "cancelled"):
        assert f"'{status}'" in sql


def test_execution_migration_creates_every_table_idempotently():
    sql = (MIGRATIONS / "006_execution.sql").read_text(encoding="utf-8")
    for table in ("execution_settings", "execution_accounts", "execution_policies",
                  "execution_positions", "execution_intents", "execution_orders",
                  "execution_fills", "execution_audit"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "ALTER TABLE backtest_jobs ADD COLUMN IF NOT EXISTS rule_id UUID" in sql


def test_execution_ships_switched_off():
    """Applying the migration must arm nothing: the brake is off and every account is."""
    sql = (MIGRATIONS / "006_execution.sql").read_text(encoding="utf-8")
    assert "enabled       BOOLEAN     NOT NULL DEFAULT FALSE" in sql
    assert "INSERT INTO execution_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING" in sql
    assert "mode                     TEXT NOT NULL DEFAULT 'off'" in sql


def test_the_constraints_that_make_double_spending_impossible_are_unique():
    """
    These indexes are the exactly-once guarantee. A Python check could not be,
    because two processes reading before either writes is a race by construction.
    """
    sql = (MIGRATIONS / "006_execution.sql").read_text(encoding="utf-8")
    # One live position per rule, per venue, per mode.
    assert "CREATE UNIQUE INDEX IF NOT EXISTS execution_positions_one_live" in sql
    assert "WHERE status IN ('opening', 'open', 'closing')" in sql
    # One intent per fire, and one exit of each kind per position.
    assert "CREATE UNIQUE INDEX IF NOT EXISTS execution_intents_one_per_event" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS execution_intents_one_exit_per_position" in sql
    # One venue write per client order id.
    assert "client_order_id TEXT NOT NULL UNIQUE" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS execution_fills_venue_unique" in sql


def test_migrations_still_sort_in_application_order():
    names = sorted(p.name for p in MIGRATIONS.glob("*.sql"))
    assert names[-1] == "006_execution.sql"
