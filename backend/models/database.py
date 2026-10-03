import asyncpg
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "db" / "migrations"


async def _register_codecs(conn: asyncpg.Connection) -> None:
    """
    Teach asyncpg to hand JSONB back as dicts.

    Without this it returns the raw JSON string, so every read site would need
    its own json.loads and one forgotten call is a confusing type error far from
    the query.
    """
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Create connection pool to TimescaleDB"""
        self.pool = await asyncpg.create_pool(
            host=settings.timescale_host,
            port=settings.timescale_port,
            database=settings.timescale_db,
            user=settings.timescale_user,
            password=settings.timescale_password,
            min_size=5,
            max_size=20,
            init=_register_codecs
        )

    async def disconnect(self):
        """Close connection pool"""
        if self.pool:
            await self.pool.close()

    async def bootstrap_schema(self):
        """
        Apply the migration files against the live database.

        init-db.sql only runs when the Postgres volume is empty, so it cannot
        deliver schema to a deployment that already has data. Every statement
        here is IF NOT EXISTS, which makes re-running on each boot a no-op.
        """
        if not MIGRATIONS_DIR.is_dir():
            return

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            async with self.pool.acquire() as conn:
                await conn.execute(path.read_text(encoding="utf-8"))

    async def execute(self, query: str, *args) -> str:
        """Execute a query"""
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args) -> List[Dict[str, Any]]:
        """Fetch multiple rows"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]

    async def fetchrow(self, query: str, *args) -> Optional[Dict[str, Any]]:
        """Fetch a single row"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None

    async def get_ohlc_data(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 240
    ) -> List[Dict[str, Any]]:
        """Fetch OHLC data from TimescaleDB"""
        query = """
            SELECT
                time,
                open,
                high,
                low,
                close,
                volume
            FROM ohlc_data
            WHERE symbol = $1 AND timeframe = $2
            ORDER BY time DESC
            LIMIT $3
        """
        data = await self.fetch(query, symbol, timeframe, limit)
        # Reverse to get chronological order
        return list(reversed(data))

    async def insert_ohlc_data(
        self,
        symbol: str,
        timeframe: str,
        data: List[Dict[str, Any]]
    ):
        """Insert OHLC data into TimescaleDB"""
        query = """
            INSERT INTO ohlc_data (time, symbol, timeframe, open, high, low, close, volume)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (time, symbol, timeframe) DO UPDATE
            SET open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume
        """
        async with self.pool.acquire() as conn:
            await conn.executemany(query, [
                (
                    row['time'],
                    symbol,
                    timeframe,
                    row['open'],
                    row['high'],
                    row['low'],
                    row['close'],
                    row['volume']
                )
                for row in data
            ])

    async def store_annotation(
        self,
        symbol: str,
        annotation: Dict[str, Any]
    ):
        """Store chart annotation"""
        query = """
            INSERT INTO annotations (symbol, annotation_data, created_at)
            VALUES ($1, $2, $3)
            RETURNING id
        """
        result = await self.fetchrow(
            query,
            symbol,
            annotation,
            datetime.utcnow()
        )
        return result['id']

    async def get_annotations(self, symbol: str) -> List[Dict[str, Any]]:
        """Get chart annotations for a symbol"""
        query = """
            SELECT id, annotation_data, created_at
            FROM annotations
            WHERE symbol = $1
            ORDER BY created_at DESC
            LIMIT 100
        """
        return await self.fetch(query, symbol)


# Global database instance
db = Database()
