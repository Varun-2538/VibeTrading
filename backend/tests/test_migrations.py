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
