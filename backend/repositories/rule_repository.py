"""
Persistence for strategy rules and their fire history.

Every owner-facing query filters on owner_key and returns nothing rather than
raising on a mismatch, so a caller cannot tell another owner's rule id from a
non-existent one.
"""
from decimal import Decimal
from typing import Any, Dict, List, Optional

from models.database import db

RULE_COLUMNS = """
    id, owner_key, owner_kind, name, agent, symbol, timeframe, params, action,
    enabled, cooldown_secs, persist_bars, pending, last_candle_time,
    last_fired_at, fire_count, created_at, updated_at
"""


class RuleRepository:
    """Strategy rule storage."""

    @staticmethod
    async def create(
        owner_key: str,
        name: str,
        agent: str,
        symbol: str,
        timeframe: str,
        params: Dict[str, Any],
        cooldown_secs: int,
        persist_bars: int,
    ) -> Dict[str, Any]:
        # owner_kind is written explicitly rather than left to the column
        # default: it records what the owner_key actually is, and a silent
        # default is the wrong place for that to be decided.
        query = f"""
            INSERT INTO strategy_rules
                (owner_key, owner_kind, name, agent, symbol, timeframe, params,
                 cooldown_secs, persist_bars)
            VALUES ($1, 'wallet', $2, $3, $4, $5, $6, $7, $8)
            RETURNING {RULE_COLUMNS}
        """
        return await db.fetchrow(
            query,
            owner_key,
            name,
            agent,
            symbol.upper(),
            timeframe,
            params,
            cooldown_secs,
            persist_bars,
        )

    @staticmethod
    async def list_for_owner(
        owner_key: str,
        symbol: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        clauses = ["owner_key = $1"]
        args: List[Any] = [owner_key]

        if symbol is not None:
            args.append(symbol.upper())
            clauses.append(f"symbol = ${len(args)}")
        if enabled is not None:
            args.append(enabled)
            clauses.append(f"enabled = ${len(args)}")

        query = f"""
            SELECT {RULE_COLUMNS} FROM strategy_rules
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC
        """
        return await db.fetch(query, *args)

    @staticmethod
    async def get_for_owner(rule_id: str, owner_key: str) -> Optional[Dict[str, Any]]:
        query = f"""
            SELECT {RULE_COLUMNS} FROM strategy_rules
            WHERE id = $1 AND owner_key = $2
        """
        return await db.fetchrow(query, rule_id, owner_key)

    @staticmethod
    async def update(
        rule_id: str,
        owner_key: str,
        fields: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Patch the given columns. Returns None when the rule is not the owner's."""
        if not fields:
            return await RuleRepository.get_for_owner(rule_id, owner_key)

        args: List[Any] = []
        assignments = []
        for column, value in fields.items():
            args.append(value)
            assignments.append(f"{column} = ${len(args)}")

        args.extend([rule_id, owner_key])
        query = f"""
            UPDATE strategy_rules
            SET {', '.join(assignments)}, updated_at = NOW()
            WHERE id = ${len(args) - 1} AND owner_key = ${len(args)}
            RETURNING {RULE_COLUMNS}
        """
        return await db.fetchrow(query, *args)

    @staticmethod
    async def delete(rule_id: str, owner_key: str) -> bool:
        query = "DELETE FROM strategy_rules WHERE id = $1 AND owner_key = $2 RETURNING id"
        return await db.fetchrow(query, rule_id, owner_key) is not None

    @staticmethod
    async def list_armed() -> List[Dict[str, Any]]:
        """Every enabled rule, for one sweep of the engine."""
        query = f"SELECT {RULE_COLUMNS} FROM strategy_rules WHERE enabled"
        return await db.fetch(query)

    @staticmethod
    async def set_pending(
        rule_id: str,
        pending: Optional[Dict[str, Any]],
        last_candle_time,
    ) -> None:
        """Record the candidate signal and the closed bar we just evaluated."""
        query = """
            UPDATE strategy_rules
            SET pending = $2, last_candle_time = $3, updated_at = NOW()
            WHERE id = $1
        """
        await db.execute(query, rule_id, pending, last_candle_time)

    @staticmethod
    async def mark_fired(rule_id: str, fired_at) -> None:
        query = """
            UPDATE strategy_rules
            SET last_fired_at = $2, fire_count = fire_count + 1, updated_at = NOW()
            WHERE id = $1
        """
        await db.execute(query, rule_id, fired_at)


class RuleEventRepository:
    """Fire history."""

    @staticmethod
    async def insert(
        rule_id: str,
        owner_key: str,
        dedup_key: str,
        symbol: str,
        timeframe: str,
        agent: str,
        direction: Optional[str],
        price: float,
        candle_time,
        provisional: bool,
        evidence: Dict[str, Any],
        action_kind: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Record a fire, or return None if this exact signal already fired.

        The UNIQUE index on dedup_key does the work: a concurrent or repeated
        sweep conflicts here instead of producing a duplicate alert.
        """
        query = """
            INSERT INTO strategy_rule_events
                (rule_id, owner_key, dedup_key, symbol, timeframe, agent,
                 direction, price, candle_time, provisional, evidence, action_kind)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (dedup_key) DO NOTHING
            RETURNING id, fired_at
        """
        return await db.fetchrow(
            query,
            rule_id,
            owner_key,
            dedup_key,
            symbol.upper(),
            timeframe,
            agent,
            direction,
            # asyncpg binds NUMERIC from Decimal only; a float raises. str()
            # first so we get the shortest exact repr rather than binary noise.
            Decimal(str(price)),
            candle_time,
            provisional,
            evidence,
            action_kind,
        )

    @staticmethod
    async def exists(dedup_key: str) -> bool:
        query = "SELECT 1 FROM strategy_rule_events WHERE dedup_key = $1"
        return await db.fetchrow(query, dedup_key) is not None

    @staticmethod
    async def set_action_result(
        event_id: int,
        status: str,
        result: Optional[Dict[str, Any]],
    ) -> None:
        query = """
            UPDATE strategy_rule_events
            SET action_status = $2, action_result = $3
            WHERE id = $1
        """
        await db.execute(query, event_id, status, result)

    @staticmethod
    async def list_for_owner(
        owner_key: str,
        rule_id: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        clauses = ["e.owner_key = $1"]
        args: List[Any] = [owner_key]

        if rule_id is not None:
            args.append(rule_id)
            clauses.append(f"e.rule_id = ${len(args)}")
        if symbol is not None:
            args.append(symbol.upper())
            clauses.append(f"e.symbol = ${len(args)}")

        args.append(limit)
        query = f"""
            SELECT e.id, e.rule_id, r.name AS rule_name, e.symbol, e.timeframe,
                   e.agent, e.direction, e.price, e.candle_time, e.fired_at,
                   e.provisional, e.evidence, e.action_kind, e.action_status
            FROM strategy_rule_events e
            LEFT JOIN strategy_rules r ON r.id = e.rule_id
            WHERE {' AND '.join(clauses)}
            ORDER BY e.fired_at DESC
            LIMIT ${len(args)}
        """
        return await db.fetch(query, *args)
