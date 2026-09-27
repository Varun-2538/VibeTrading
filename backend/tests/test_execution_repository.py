"""
The SQL that enforces the rules, asserted as text.

There is no database in the test run, so this is the only place the claiming
statement can be checked at all - and it is worth checking, because every cap in the
system is enforced inside it. A cap moved into Python would still pass every other
test in the suite and would be a race the moment two processes existed.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repositories.execution_repository import (
    ACCOUNT_COLUMNS,
    CLAIM_SQL,
    INTENT_COLUMNS,
    LIVE_STATUSES,
    POLICY_COLUMNS,
    POSITION_COLUMNS,
)


class TestClaim:
    def test_it_locks_only_the_intent_row(self):
        """
        A bare FOR UPDATE would also lock the singleton settings row, which would
        serialise every claim in the system behind one another.
        """
        assert "FOR UPDATE OF c SKIP LOCKED" in CLAIM_SQL
        assert "FOR UPDATE SKIP LOCKED" not in CLAIM_SQL.replace("FOR UPDATE OF c SKIP LOCKED", "")

    def test_exits_are_ordered_ahead_of_entries(self):
        """A queue that let a new entry overtake an unplaced exit is the wrong queue."""
        assert "ORDER BY (c.kind = 'entry'), c.created_at" in CLAIM_SQL

    def test_every_cap_is_checked_in_the_statement(self):
        for fragment in (
            "s.enabled",
            "NOT a.kill_switch",
            "a.mode <> 'off'",
            "a.max_concurrent_positions",
            "a.max_trades_per_day",
            "a.daily_loss_limit_usd",
        ):
            assert fragment in CLAIM_SQL, fragment

    def test_the_caps_apply_to_entries_only(self):
        """
        A kill switch that stopped you closing a position would be a trap rather than
        a safety rail: caps limit what can be opened, and an exit only ever reduces
        exposure.
        """
        assert "AND (c.kind <> 'entry' OR (" in CLAIM_SQL

    def test_a_halt_stops_claims_in_both_directions(self):
        assert "a.halted_reason IS NULL" in CLAIM_SQL
        assert "s.halted_reason IS NULL" in CLAIM_SQL

    def test_the_day_is_utc_on_both_windows(self):
        """
        NOW() renders in the session timezone, which this compose file does not
        guarantee is UTC - so a naive date_trunc would roll the daily counters at the
        wrong hour.
        """
        assert CLAIM_SQL.count("AT TIME ZONE 'UTC'") == 4

    def test_a_shadow_intent_can_never_be_executed_live(self):
        """Not even after the owner flips the switch while it sits in the queue."""
        assert "a.mode = c.mode" in CLAIM_SQL

    def test_it_will_not_claim_something_too_late_to_be_the_same_trade(self):
        assert "c.not_after > NOW()" in CLAIM_SQL

    def test_it_counts_attempts(self):
        assert "attempts = attempts + 1" in CLAIM_SQL


class TestColumns:
    def test_the_column_lists_name_what_the_code_reads(self):
        for column in ("plan", "reference", "sizing", "parity_version", "not_after", "attempts"):
            assert column in INTENT_COLUMNS
        for column in ("stop_price", "target_price", "deadline_bar_time", "triggers_placed",
                       "realised_r", "reference"):
            assert column in POSITION_COLUMNS
        for column in ("armed", "exit_plan", "policy", "backtest_job_id", "preflight"):
            assert column in POLICY_COLUMNS
        for column in ("mode", "kill_switch", "halted_reason", "daily_loss_limit_usd"):
            assert column in ACCOUNT_COLUMNS

    def test_live_means_the_same_three_things_everywhere(self):
        assert LIVE_STATUSES == ("opening", "open", "closing")
        assert "status IN ('opening', 'open', 'closing')" in CLAIM_SQL


class TestIdempotentWrites:
    """
    The conflict clauses, which are where exactly-once actually lives. Asserted on
    the source because the indexes they name are in 006_execution.sql and the pairing
    is the thing that has to stay true.
    """

    def source(self) -> str:
        return (Path(__file__).resolve().parents[1] / "repositories" / "execution_repository.py").read_text(
            encoding="utf-8"
        )

    def test_one_intent_per_fire(self):
        assert "ON CONFLICT (event_id) WHERE event_id IS NOT NULL DO NOTHING" in self.source()

    def test_one_exit_of_each_kind_per_position(self):
        assert "ON CONFLICT (position_id, kind) WHERE position_id IS NOT NULL AND kind <> 'entry'" in self.source()

    def test_one_order_per_client_order_id(self):
        assert "ON CONFLICT (client_order_id) DO NOTHING" in self.source()

    def test_one_fill_per_venue_fill_id(self):
        assert "ON CONFLICT (venue, venue_fill_id) DO NOTHING" in self.source()

    def test_a_halt_is_not_cleared_by_saving_settings(self):
        """
        The upsert must not touch halted_reason: an owner clearing a halt by saving
        their caps would defeat the only signal reconciliation has.
        """
        source = self.source()
        statement = source.split("INSERT INTO execution_accounts")[1].split("RETURNING")[0]
        assert "halted_reason" not in statement
