"""
Execution accounts and armed policies.

Owner-facing reads filter on owner_key and return nothing on a mismatch, like the
rule and backtest repositories, so a rule id cannot be probed across wallets.

Two things are deliberately not here yet: intents and orders. They arrive with the
executor, because a queue with no consumer is a place for rows to rot.
"""
from typing import Any, Dict, List, Optional

from models.database import db

ACCOUNT_COLUMNS = """
    owner_key, mode, kill_switch, equity_usd, max_notional_usd,
    max_concurrent_positions, max_trades_per_day, daily_loss_limit_usd,
    halted_reason, halted_at, created_at, updated_at
"""

POLICY_COLUMNS = """
    rule_id, owner_key, armed, venue, market, exit_plan, policy, parity_version,
    backtest_job_id, preflight, armed_at, disarmed_reason, created_at, updated_at
"""


class ExecutionSettingsRepository:
    """The one global brake. Read at claim time, never cached at boot."""

    @staticmethod
    async def get() -> Dict[str, Any]:
        row = await db.fetchrow("SELECT enabled, halted_reason, updated_at FROM execution_settings WHERE id = 1")
        # A missing row means the migration has not run; treat that as off rather
        # than as permission.
        return row or {"enabled": False, "halted_reason": "execution_settings row missing", "updated_at": None}


class ExecutionAccountRepository:
    @staticmethod
    async def get(owner_key: str) -> Optional[Dict[str, Any]]:
        return await db.fetchrow(
            f"SELECT {ACCOUNT_COLUMNS} FROM execution_accounts WHERE owner_key = $1", owner_key
        )

    @staticmethod
    async def upsert(owner_key: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create or replace this wallet's rails.

        halted_reason is never written here: it is set by reconciliation and
        cleared by its own call, so an owner cannot clear a halt by saving their
        settings.
        """
        return await db.fetchrow(
            f"""
            INSERT INTO execution_accounts (
                owner_key, mode, equity_usd, max_notional_usd,
                max_concurrent_positions, max_trades_per_day, daily_loss_limit_usd
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (owner_key) DO UPDATE SET
                mode = EXCLUDED.mode,
                equity_usd = EXCLUDED.equity_usd,
                max_notional_usd = EXCLUDED.max_notional_usd,
                max_concurrent_positions = EXCLUDED.max_concurrent_positions,
                max_trades_per_day = EXCLUDED.max_trades_per_day,
                daily_loss_limit_usd = EXCLUDED.daily_loss_limit_usd,
                updated_at = NOW()
            RETURNING {ACCOUNT_COLUMNS}
            """,
            owner_key,
            settings["mode"],
            settings["equity_usd"],
            settings["max_notional_usd"],
            settings["max_concurrent_positions"],
            settings["max_trades_per_day"],
            settings["daily_loss_limit_usd"],
        )

    @staticmethod
    async def halt(owner_key: str, reason: str) -> Optional[Dict[str, Any]]:
        """
        Stop this account opening anything, and say why.

        Set by reconciliation when it finds something it cannot explain, and cleared
        only by a person - never by the owner saving their settings, and never by
        the process that set it. An account halted this way keeps closing positions.
        """
        return await db.fetchrow(
            f"UPDATE execution_accounts SET halted_reason = $2, halted_at = NOW(), "
            f"updated_at = NOW() WHERE owner_key = $1 RETURNING {ACCOUNT_COLUMNS}",
            owner_key, reason,
        )

    @staticmethod
    async def clear_halt(owner_key: str) -> Optional[Dict[str, Any]]:
        return await db.fetchrow(
            f"UPDATE execution_accounts SET halted_reason = NULL, halted_at = NULL, "
            f"updated_at = NOW() WHERE owner_key = $1 RETURNING {ACCOUNT_COLUMNS}",
            owner_key,
        )

    @staticmethod
    async def set_kill_switch(owner_key: str, on: bool) -> Optional[Dict[str, Any]]:
        return await db.fetchrow(
            f"UPDATE execution_accounts SET kill_switch = $2, updated_at = NOW() "
            f"WHERE owner_key = $1 RETURNING {ACCOUNT_COLUMNS}",
            owner_key,
            on,
        )


class ExecutionPolicyRepository:
    @staticmethod
    async def get(rule_id: str, owner_key: str) -> Optional[Dict[str, Any]]:
        return await db.fetchrow(
            f"SELECT {POLICY_COLUMNS} FROM execution_policies WHERE rule_id = $1 AND owner_key = $2",
            rule_id,
            owner_key,
        )

    @staticmethod
    async def list_for_owner(owner_key: str) -> List[Dict[str, Any]]:
        return await db.fetch(
            f"SELECT {POLICY_COLUMNS} FROM execution_policies WHERE owner_key = $1 "
            f"ORDER BY updated_at DESC",
            owner_key,
        )

    @staticmethod
    async def arm(
        rule_id: str,
        owner_key: str,
        *,
        venue: str,
        market: str,
        exit_plan: Dict[str, Any],
        policy: Dict[str, Any],
        parity_version: int,
        backtest_job_id: str,
        preflight: Dict[str, Any],
    ) -> Dict[str, Any]:
        return await db.fetchrow(
            f"""
            INSERT INTO execution_policies (
                rule_id, owner_key, armed, venue, market, exit_plan, policy,
                parity_version, backtest_job_id, preflight, armed_at, disarmed_reason
            ) VALUES ($1, $2, TRUE, $3, $4, $5, $6, $7, $8, $9, NOW(), NULL)
            ON CONFLICT (rule_id) DO UPDATE SET
                armed = TRUE,
                venue = EXCLUDED.venue,
                market = EXCLUDED.market,
                exit_plan = EXCLUDED.exit_plan,
                policy = EXCLUDED.policy,
                parity_version = EXCLUDED.parity_version,
                backtest_job_id = EXCLUDED.backtest_job_id,
                preflight = EXCLUDED.preflight,
                armed_at = NOW(),
                disarmed_reason = NULL,
                updated_at = NOW()
            RETURNING {POLICY_COLUMNS}
            """,
            rule_id,
            owner_key,
            venue,
            market,
            exit_plan,
            policy,
            parity_version,
            backtest_job_id,
            preflight,
        )

    @staticmethod
    async def disarm(rule_id: str, reason: str, owner_key: Optional[str] = None) -> bool:
        """
        Stop a rule opening anything new, and say why.

        owner_key is optional because the server disarms too - a rule whose
        settings changed is no longer the rule that passed its gate, and that
        happens on the owner's own PATCH but is not their decision.
        """
        clause = "AND owner_key = $3" if owner_key else ""
        args = [rule_id, reason] + ([owner_key] if owner_key else [])
        row = await db.fetchrow(
            f"""
            UPDATE execution_policies
            SET armed = FALSE, disarmed_reason = $2, updated_at = NOW()
            WHERE rule_id = $1 AND armed {clause}
            RETURNING rule_id
            """,
            *args,
        )
        return row is not None


INTENT_COLUMNS = """
    id, owner_key, rule_id, event_id, position_id, kind, status, mode, venue, market,
    side, plan, reference, sizing, parity_version, not_after, attempts, claimed_at,
    claimed_by, finished_at, error, created_at
"""

POSITION_COLUMNS = """
    id, owner_key, rule_id, venue, market, symbol, timeframe, direction, status, mode,
    entry_intent_id, entry_event_id, plan, parity_version, signal_bar_time,
    entry_bar_time, entry_price, qty, notional_usd, stop_price, target_price,
    deadline_bar_time, triggers_placed, exit_price, exit_reason, closed_at,
    realised_pnl_usd, realised_r, reference, reconciled_at, opened_at, updated_at
"""

LIVE_STATUSES = ("opening", "open", "closing")

# Caps are enforced *in this statement*, not in Python. A read-then-act check is a
# race the moment two processes exist, and the point of the queue is to be correct
# even then.
#
# Three details are load-bearing:
#   FOR UPDATE OF c  - a bare FOR UPDATE would also lock the singleton settings row
#                      and serialise every claim in the system.
#   AT TIME ZONE 'UTC' on both date_truncs - NOW() renders in the session timezone,
#                      which this compose file does not guarantee is UTC.
#   a.mode = c.mode  - an intent queued in shadow can never be executed live after
#                      the owner flips the switch.
#
# And exits are gated on nothing at all. A kill switch that stopped you closing a
# position would be a trap rather than a safety rail: caps exist to limit what can
# be opened, and an exit only ever reduces exposure.
CLAIM_SQL = f"""
UPDATE execution_intents
SET status = 'claimed', claimed_at = NOW(), claimed_by = $1, attempts = attempts + 1
WHERE id = (
    SELECT c.id
    FROM execution_intents c
    JOIN execution_accounts a ON a.owner_key = c.owner_key
    CROSS JOIN execution_settings s
    WHERE c.status = 'queued'
      AND c.not_after > NOW()
      AND a.mode = c.mode
      AND a.halted_reason IS NULL
      AND s.halted_reason IS NULL
      AND (c.kind <> 'entry' OR (
              s.enabled
          AND NOT a.kill_switch
          AND a.mode <> 'off'
          AND (SELECT count(*) FROM execution_positions p
                WHERE p.owner_key = c.owner_key AND p.mode = c.mode
                  AND p.status IN ('opening', 'open', 'closing'))
              < a.max_concurrent_positions
          AND (SELECT count(*) FROM execution_positions p
                WHERE p.owner_key = c.owner_key AND p.mode = c.mode
                  AND p.opened_at >= date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')
              < a.max_trades_per_day
          AND COALESCE((SELECT sum(p.realised_pnl_usd) FROM execution_positions p
                WHERE p.owner_key = c.owner_key AND p.mode = c.mode AND p.status = 'closed'
                  AND p.closed_at >= date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'), 0)
              > -a.daily_loss_limit_usd
      ))
    ORDER BY (c.kind = 'entry'), c.created_at
    FOR UPDATE OF c SKIP LOCKED
    LIMIT 1
)
RETURNING {INTENT_COLUMNS}
"""


class ExecutionIntentRepository:
    @staticmethod
    async def queue_from_event(
        *,
        owner_key: str,
        rule_id: str,
        event_id: int,
        kind: str,
        mode: str,
        venue: str,
        market: str,
        side: str,
        plan: Dict[str, Any],
        reference: Dict[str, Any],
        parity_version: int,
        not_after: Any,
        position_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Turn a fire into an intent, once.

        None means this event already has one, which is what makes the promotion
        loop safe to re-run - and what stops a second sweep, or a loop replayed
        after a restart, from queueing the same fire twice.
        """
        return await db.fetchrow(
            f"""
            INSERT INTO execution_intents (
                owner_key, rule_id, event_id, position_id, kind, mode, venue, market,
                side, plan, reference, parity_version, not_after
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (event_id) WHERE event_id IS NOT NULL DO NOTHING
            RETURNING {INTENT_COLUMNS}
            """,
            owner_key, rule_id, event_id, position_id, kind, mode, venue, market,
            side, plan, reference, parity_version, not_after,
        )

    @staticmethod
    async def queue_exit(
        *,
        owner_key: str,
        rule_id: str,
        position_id: str,
        kind: str,
        mode: str,
        venue: str,
        market: str,
        side: str,
        plan: Dict[str, Any],
        reference: Dict[str, Any],
        parity_version: int,
        not_after: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        One exit of each kind per position, ever.

        None means it is already queued. Without that, a monitor tick that ran
        twice across a restart would queue two flattens, and the second one would
        open a reverse position.
        """
        return await db.fetchrow(
            f"""
            INSERT INTO execution_intents (
                owner_key, rule_id, position_id, kind, mode, venue, market, side,
                plan, reference, parity_version, not_after
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (position_id, kind) WHERE position_id IS NOT NULL AND kind <> 'entry'
            DO NOTHING
            RETURNING {INTENT_COLUMNS}
            """,
            owner_key, rule_id, position_id, kind, mode, venue, market, side,
            plan, reference, parity_version, not_after,
        )

    @staticmethod
    async def get(intent_id: str) -> Optional[Dict[str, Any]]:
        return await db.fetchrow(
            f"SELECT {INTENT_COLUMNS} FROM execution_intents WHERE id = $1", intent_id
        )

    @staticmethod
    async def queued_events(limit: int = 20) -> List[Dict[str, Any]]:
        """
        Fires that the sweep handed over and nobody has turned into an intent yet.

        The join is what makes the sweep's job end at one row: it writes 'queued' on
        the event and this reads it back, so a slow executor cannot slow the alerts.
        """
        return await db.fetch(
            """
            SELECT e.id AS event_id, e.rule_id, e.owner_key, e.action_result, e.fired_at,
                   a.mode AS account_mode
            FROM strategy_rule_events e
            JOIN execution_accounts a ON a.owner_key = e.owner_key
            LEFT JOIN execution_intents i ON i.event_id = e.id
            WHERE e.action_kind = 'dex_trade' AND e.action_status = 'queued'
              AND i.id IS NULL
            ORDER BY e.fired_at
            LIMIT $1
            """,
            limit,
        )

    @staticmethod
    async def claim(claimed_by: str) -> Optional[Dict[str, Any]]:
        return await db.fetchrow(CLAIM_SQL, claimed_by)

    @staticmethod
    async def finish(intent_id: str, status: str, error: Optional[str] = None) -> None:
        await db.execute(
            "UPDATE execution_intents SET status = $2, error = $3, finished_at = NOW() WHERE id = $1",
            intent_id, status, error,
        )

    @staticmethod
    async def requeue(intent_id: str, error: Optional[str] = None) -> None:
        """
        Back on the queue, for a failure that definitely did not execute.

        Never used after a timeout: that is what needs_reconcile is for, because
        retrying an unknown outcome is how you spend twice.
        """
        await db.execute(
            "UPDATE execution_intents SET status = 'queued', error = $2, claimed_at = NULL, "
            "claimed_by = NULL WHERE id = $1",
            intent_id, error,
        )

    @staticmethod
    async def set_sizing(intent_id: str, sizing: Dict[str, Any]) -> None:
        await db.execute("UPDATE execution_intents SET sizing = $2 WHERE id = $1", intent_id, sizing)

    @staticmethod
    async def list_for_owner(
        owner_key: str, status: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        clause = "AND status = $2" if status else ""
        args: List[Any] = [owner_key] + ([status] if status else [])
        args.append(limit)
        return await db.fetch(
            f"SELECT {INTENT_COLUMNS} FROM execution_intents WHERE owner_key = $1 {clause} "
            f"ORDER BY created_at DESC LIMIT ${len(args)}",
            *args,
        )

    @staticmethod
    async def stuck(older_than_seconds: int = 300) -> List[Dict[str, Any]]:
        """Claimed but never finished: what a crash looks like from the outside."""
        return await db.fetch(
            f"SELECT {INTENT_COLUMNS} FROM execution_intents "
            f"WHERE status IN ('claimed', 'submitting') "
            f"AND claimed_at < NOW() - ($1 || ' seconds')::interval",
            str(older_than_seconds),
        )


class ExecutionPositionRepository:
    @staticmethod
    async def open_for_rule(owner_key: str, rule_id: str, mode: str) -> Optional[Dict[str, Any]]:
        return await db.fetchrow(
            f"SELECT {POSITION_COLUMNS} FROM execution_positions "
            f"WHERE owner_key = $1 AND rule_id = $2 AND mode = $3 "
            f"AND status IN ('opening', 'open', 'closing')",
            owner_key, rule_id, mode,
        )

    @staticmethod
    async def create(**kw: Any) -> Optional[Dict[str, Any]]:
        """
        None when this rule already has a live position: the unique index refused.

        That index, not this code, is what stops two executors doubling a position
        - which is also what keeps live faithful to the simulation, since
        backtest/trades.py holds one at a time.
        """
        return await db.fetchrow(
            f"""
            INSERT INTO execution_positions (
                owner_key, rule_id, venue, market, symbol, timeframe, direction, status,
                mode, entry_intent_id, entry_event_id, plan, parity_version,
                signal_bar_time, entry_bar_time, entry_price, qty, notional_usd,
                stop_price, target_price, deadline_bar_time, triggers_placed, reference
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
                      $16, $17, $18, $19, $20, $21, $22, $23)
            ON CONFLICT DO NOTHING
            RETURNING {POSITION_COLUMNS}
            """,
            kw["owner_key"], kw["rule_id"], kw["venue"], kw["market"], kw["symbol"],
            kw["timeframe"], kw["direction"], kw.get("status", "open"), kw["mode"],
            kw["entry_intent_id"], kw.get("entry_event_id"), kw["plan"], kw["parity_version"],
            kw["signal_bar_time"], kw.get("entry_bar_time"), kw.get("entry_price"),
            kw.get("qty"), kw.get("notional_usd"), kw["stop_price"], kw.get("target_price"),
            kw["deadline_bar_time"], kw.get("triggers_placed", True), kw.get("reference"),
        )

    @staticmethod
    async def live(mode: Optional[str] = None) -> List[Dict[str, Any]]:
        clause = "AND mode = $1" if mode else ""
        args = [mode] if mode else []
        return await db.fetch(
            f"SELECT {POSITION_COLUMNS} FROM execution_positions "
            f"WHERE status IN ('opening', 'open', 'closing') {clause} "
            f"ORDER BY deadline_bar_time",
            *args,
        )

    @staticmethod
    async def get(position_id: str, owner_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
        clause = "AND owner_key = $2" if owner_key else ""
        args = [position_id] + ([owner_key] if owner_key else [])
        return await db.fetchrow(
            f"SELECT {POSITION_COLUMNS} FROM execution_positions WHERE id = $1 {clause}", *args
        )

    @staticmethod
    async def list_for_owner(owner_key: str, limit: int = 50) -> List[Dict[str, Any]]:
        return await db.fetch(
            f"SELECT {POSITION_COLUMNS} FROM execution_positions WHERE owner_key = $1 "
            f"ORDER BY opened_at DESC LIMIT $2",
            owner_key, limit,
        )

    @staticmethod
    async def mark_closing(position_id: str) -> bool:
        row = await db.fetchrow(
            "UPDATE execution_positions SET status = 'closing', updated_at = NOW() "
            "WHERE id = $1 AND status IN ('opening', 'open') RETURNING id",
            position_id,
        )
        return row is not None

    @staticmethod
    async def close(
        position_id: str,
        *,
        exit_price: float,
        exit_reason: str,
        realised_pnl_usd: float,
        realised_r: float,
        reference: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        return await db.fetchrow(
            f"""
            UPDATE execution_positions
            SET status = 'closed', exit_price = $2, exit_reason = $3, closed_at = NOW(),
                realised_pnl_usd = $4, realised_r = $5,
                reference = COALESCE($6, reference), updated_at = NOW()
            WHERE id = $1 AND status <> 'closed'
            RETURNING {POSITION_COLUMNS}
            """,
            position_id, exit_price, exit_reason, realised_pnl_usd, realised_r, reference,
        )

    @staticmethod
    async def abandon(position_id: str, reason: str) -> None:
        await db.execute(
            "UPDATE execution_positions SET status = 'abandoned', exit_reason = 'reconciled', "
            "closed_at = NOW(), updated_at = NOW() WHERE id = $1 AND status <> 'closed'",
            position_id,
        )

    @staticmethod
    async def closed_count(owner_key: str, mode: str) -> int:
        row = await db.fetchrow(
            "SELECT count(*) AS n FROM execution_positions "
            "WHERE owner_key = $1 AND mode = $2 AND status = 'closed'",
            owner_key, mode,
        )
        return int(row["n"]) if row else 0


class ExecutionOrderRepository:
    @staticmethod
    async def submit(
        *,
        owner_key: str,
        intent_id: str,
        position_id: Optional[str],
        client_order_id: str,
        leg: str,
        kind: str,
        side: str,
        qty: Optional[float],
        request: Dict[str, Any],
        reduce_only: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Written *before* the venue is called, so "the process died inside the swap"
        is a readable state rather than a gap. None means this exact write was
        already sent once - the retry refusing itself.
        """
        return await db.fetchrow(
            """
            INSERT INTO execution_orders (
                owner_key, intent_id, position_id, client_order_id, leg, kind, side,
                reduce_only, qty, request
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (client_order_id) DO NOTHING
            RETURNING id, client_order_id, status
            """,
            owner_key, intent_id, position_id, client_order_id, leg, kind, side,
            reduce_only, qty, request,
        )

    @staticmethod
    async def ack(
        order_id: int,
        status: str,
        venue_order_id: Optional[str] = None,
        response: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """The only update this table has; everything else about it is insert-only."""
        await db.execute(
            "UPDATE execution_orders SET status = $2, venue_order_id = $3, response = $4, "
            "error = $5, acked_at = NOW() WHERE id = $1",
            order_id, status, venue_order_id, response, error,
        )

    @staticmethod
    async def in_doubt() -> List[Dict[str, Any]]:
        """Writes whose outcome we never learned. Reconciliation starts here."""
        return await db.fetch(
            "SELECT id, owner_key, intent_id, position_id, client_order_id, leg, qty, "
            "status, submitted_at, request FROM execution_orders "
            "WHERE status IN ('submitting', 'unknown') ORDER BY submitted_at"
        )

    @staticmethod
    async def for_intent(intent_id: str) -> List[Dict[str, Any]]:
        return await db.fetch(
            "SELECT id, client_order_id, leg, status, venue_order_id, submitted_at, acked_at, "
            "request, response, error FROM execution_orders WHERE intent_id = $1 "
            "ORDER BY submitted_at",
            intent_id,
        )


class ExecutionFillRepository:
    @staticmethod
    async def record(
        *,
        owner_key: str,
        order_id: int,
        position_id: Optional[str],
        venue: str,
        venue_fill_id: str,
        price: float,
        qty: float,
        fee_usd: float,
        gas_usd: float,
        filled_at: Any,
        raw: Dict[str, Any],
        tx_ref: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        None means this fill is already booked. The venue's own id is the key, so a
        positions poll replayed after a restart cannot book it twice.
        """
        return await db.fetchrow(
            """
            INSERT INTO execution_fills (
                owner_key, order_id, position_id, venue, venue_fill_id, price, qty,
                fee_usd, gas_usd, tx_ref, filled_at, raw
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (venue, venue_fill_id) DO NOTHING
            RETURNING id, price, qty
            """,
            owner_key, order_id, position_id, venue, venue_fill_id, price, qty,
            fee_usd, gas_usd, tx_ref, filled_at, raw,
        )

    @staticmethod
    async def for_position(position_id: str) -> List[Dict[str, Any]]:
        return await db.fetch(
            "SELECT id, price, qty, fee_usd, gas_usd, tx_ref, filled_at, venue_fill_id "
            "FROM execution_fills WHERE position_id = $1 ORDER BY filled_at",
            position_id,
        )


class ExecutionAuditRepository:
    @staticmethod
    async def record(
        *,
        owner_key: str,
        actor: str,
        reason: str,
        intent_id: Optional[str] = None,
        position_id: Optional[str] = None,
        order_id: Optional[int] = None,
        from_status: Optional[str] = None,
        to_status: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        await db.execute(
            "INSERT INTO execution_audit (owner_key, intent_id, position_id, order_id, "
            "actor, from_status, to_status, reason, detail) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
            owner_key, intent_id, position_id, order_id, actor, from_status, to_status,
            reason, detail,
        )

    @staticmethod
    async def for_position(position_id: str) -> List[Dict[str, Any]]:
        return await db.fetch(
            "SELECT at, actor, from_status, to_status, reason, detail FROM execution_audit "
            "WHERE position_id = $1 ORDER BY at",
            position_id,
        )
