"""
Backtest jobs and candidate tapes.

Owner-facing reads filter on owner_key and return nothing on a mismatch, like
the rule repository, so a job id cannot be probed across wallets. Writes from
the worker never overwrite 'cancelled': the API can cancel at any moment and
the worker only notices between chunks.
"""
import gzip
import json
from typing import Any, Dict, List, Optional

from models.database import db

ACTIVE_STATUSES = ("queued", "replaying", "studying", "tuning")

JOB_COLUMNS = """
    id, owner_key, rule_id, created_at, started_at, finished_at, status, progress,
    request, report, error
"""
SUMMARY_COLUMNS = """
    id, created_at, started_at, finished_at, status, progress, request, error
"""


def encode_tape(rows: List[Any]) -> bytes:
    return gzip.compress(json.dumps(rows, separators=(",", ":")).encode("utf-8"), compresslevel=6)


def decode_tape(blob: bytes) -> List[Any]:
    return json.loads(gzip.decompress(bytes(blob)).decode("utf-8"))


class BacktestRepository:
    @staticmethod
    async def create(
        owner_key: str, request: Dict[str, Any], rule_id: Optional[str] = None
    ) -> Dict[str, Any]:
        return await db.fetchrow(
            "INSERT INTO backtest_jobs (owner_key, request, rule_id) VALUES ($1, $2, $3) "
            "RETURNING id, status, created_at",
            owner_key,
            request,
            rule_id,
        )

    @staticmethod
    async def count_active(owner_key: str) -> int:
        row = await db.fetchrow(
            "SELECT count(*) AS n FROM backtest_jobs WHERE owner_key = $1 AND status = ANY($2::text[])",
            owner_key,
            list(ACTIVE_STATUSES),
        )
        return int(row["n"])

    @staticmethod
    async def get_for_owner(job_id: str, owner_key: str) -> Optional[Dict[str, Any]]:
        return await db.fetchrow(
            f"SELECT {JOB_COLUMNS} FROM backtest_jobs WHERE id = $1 AND owner_key = $2",
            job_id,
            owner_key,
        )

    @staticmethod
    async def list_for_owner(owner_key: str, limit: int = 20) -> List[Dict[str, Any]]:
        return await db.fetch(
            f"SELECT {SUMMARY_COLUMNS} FROM backtest_jobs WHERE owner_key = $1 "
            "ORDER BY created_at DESC LIMIT $2",
            owner_key,
            limit,
        )

    @staticmethod
    async def cancel_or_delete(job_id: str, owner_key: str) -> Optional[str]:
        cancelled = await db.fetchrow(
            "UPDATE backtest_jobs SET status = 'cancelled', finished_at = NOW() "
            "WHERE id = $1 AND owner_key = $2 AND status = ANY($3::text[]) RETURNING id",
            job_id,
            owner_key,
            list(ACTIVE_STATUSES),
        )
        if cancelled:
            return "cancelled"
        deleted = await db.fetchrow(
            "DELETE FROM backtest_jobs WHERE id = $1 AND owner_key = $2 RETURNING id",
            job_id,
            owner_key,
        )
        return "deleted" if deleted else None

    @staticmethod
    async def claim_next() -> Optional[Dict[str, Any]]:
        return await db.fetchrow(
            f"""
            UPDATE backtest_jobs
            SET status = 'replaying', started_at = NOW(), progress = 0
            WHERE id = (
                SELECT id FROM backtest_jobs WHERE status = 'queued'
                ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
            )
            RETURNING {JOB_COLUMNS}
            """
        )

    @staticmethod
    async def requeue_running() -> int:
        rows = await db.fetch(
            "UPDATE backtest_jobs SET status = 'queued', progress = 0 "
            "WHERE status IN ('replaying', 'studying', 'tuning') RETURNING id"
        )
        return len(rows)

    @staticmethod
    async def status_of(job_id: str) -> Optional[str]:
        row = await db.fetchrow("SELECT status FROM backtest_jobs WHERE id = $1", job_id)
        return row["status"] if row else None

    @staticmethod
    async def set_progress(job_id: str, status: str, progress: float) -> None:
        await db.execute(
            "UPDATE backtest_jobs SET status = $2, progress = $3 WHERE id = $1 AND status <> 'cancelled'",
            job_id,
            status,
            progress,
        )

    @staticmethod
    async def finish(job_id: str, report: Dict[str, Any]) -> None:
        await db.execute(
            "UPDATE backtest_jobs SET status = 'done', progress = 1, report = $2, finished_at = NOW() "
            "WHERE id = $1 AND status <> 'cancelled'",
            job_id,
            report,
        )

    @staticmethod
    async def fail(job_id: str, error: str) -> None:
        await db.execute(
            "UPDATE backtest_jobs SET status = 'failed', error = $2, finished_at = NOW() "
            "WHERE id = $1 AND status <> 'cancelled'",
            job_id,
            error,
        )

    @staticmethod
    async def get_tape(key: str) -> Optional[List[Any]]:
        row = await db.fetchrow("SELECT rows FROM signal_tapes WHERE key = $1", key)
        return decode_tape(row["rows"]) if row else None

    @staticmethod
    async def put_tape(key: str, bars: int, rows: List[Any]) -> None:
        await db.execute(
            "INSERT INTO signal_tapes (key, bars, rows) VALUES ($1, $2, $3) "
            "ON CONFLICT (key) DO UPDATE SET rows = EXCLUDED.rows, bars = EXCLUDED.bars, created_at = NOW()",
            key,
            bars,
            encode_tape(rows),
        )

    @staticmethod
    async def evict_tapes(older_than_days: int = 14) -> None:
        await db.execute(
            "DELETE FROM signal_tapes WHERE created_at < NOW() - make_interval(days => $1)",
            older_than_days,
        )
