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
