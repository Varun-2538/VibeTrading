# Backtesting Slice 1: History Store — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store and keep current the candle history backtests will run on — 9 pairs × 5m (6 months), 15m (1 year), 1h (3 years), 1d (all) — in TimescaleDB, with a public coverage endpoint, filled and topped up by a new low-priority worker container.

**Architecture:** A hypertable `candles_history` is added by an idempotent migration. `services/history_service.py` holds pure helpers (depths, kline parsing, gap counting), a retrying Binance page fetcher, and `backfill()` which resumes from the newest stored bar and trims past the depth. `repositories/history_repository.py` owns the SQL. A new `worker.py` process (same Docker image, its own `backtester` compose service at low CPU share) runs `topup_all()` at start and hourly; later slices add the backtest job loop to this same worker. `GET /api/history/coverage` reports what exists.

**Tech Stack:** Python 3.11, FastAPI, asyncpg, TimescaleDB (pg15), httpx, APScheduler 3 (AsyncIOScheduler), pytest + pytest-asyncio (`asyncio_mode = auto`), Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-17-backtesting-design.md` (sections "History store", "Error handling", "Testing → History", "Slices → 1").

## Global Constraints

- Depths: `5m` 183 days, `15m` 365 days, `1h` 1095 days, `1d` all available (since listing).
- Pairs: `BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, DOTUSDT, AVAXUSDT`.
- Candle shape everywhere outside SQL: `{"time": int unix ms (open time), "open": float, "high": float, "low": float, "close": float, "volume": float}`, oldest first — identical to `CandleService.get_candles`.
- Only **closed** bars are stored (Binance kline close time `row[6]` < now).
- Gaps are **counted and reported, never filled** with invented bars.
- Binance: `GET https://api.binance.com/api/v3/klines`, `limit=1000`, paged by `startTime`; back off on HTTP 429/418 honouring `Retry-After`; retry 5xx with exponential backoff; pause between pages.
- Migrations live in `backend/db/migrations/`, are applied on every boot by `Database.bootstrap_schema()`, and **must be idempotent** (`IF NOT EXISTS`, `if_not_exists => TRUE`).
- `config.settings.Settings` requires `LLM_API_KEY`, `DATABASE_URL`, `TIMESCALE_USER`, `TIMESCALE_PASSWORD`, `JWT_SECRET` at import — the worker container needs the same environment as `backend`.
- The worker must never compete with live alerts: compose `cpu_shares: 256` (backend default 1024).
- Commits end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. Scan staged diffs for `csk-`, `gsk_`, `JWT_SECRET=` before committing.

**Running tests.** From `backend/`, with a Python 3.11 environment that has `requirements.txt` + `pytest pytest-asyncio` installed (the checked-in `.venv` points at a removed interpreter; recreate with `uv venv --python 3.11 .venv && uv pip install --python .venv/Scripts/python.exe -r requirements.txt pytest pytest-asyncio`):

```
.venv/Scripts/python.exe -m pytest -q
```

Baseline before this plan: **308 passed**.

## File Structure

| File | Responsibility |
|---|---|
| Create `backend/db/migrations/004_candles_history.sql` | The hypertable. |
| Create `backend/services/history_service.py` | Constants, pure helpers, retrying page fetch, `backfill`, `topup_all`. No SQL. |
| Create `backend/repositories/history_repository.py` | All SQL for `candles_history`: upsert, newest time, load, trim, coverage. |
| Create `backend/controllers/history_controller.py` | `GET /api/history/coverage`. |
| Modify `backend/controllers/__init__.py`, `backend/main.py` | Register the router. |
| Create `backend/scripts/__init__.py`, `backend/scripts/backfill_history.py` | Manual CLI fill. |
| Create `backend/worker.py` | Worker process: DB connect, schema, heartbeat, hourly top-up. |
| Modify `docker-compose.prod.yml` | `backtester` service sharing backend's env. |
| Create `backend/tests/test_history_service.py`, `backend/tests/test_history_controller.py`, `backend/tests/test_worker.py`, `backend/tests/test_migrations.py` | Tests. |
| Modify `backend/tests/test_app_imports.py` | Add the new controller. |

---

### Task 1: The `candles_history` hypertable migration

**Files:**
- Create: `backend/db/migrations/004_candles_history.sql`
- Test: `backend/tests/test_migrations.py`

**Interfaces:**
- Produces: table `candles_history(symbol text, timeframe text, time timestamptz, open, high, low, close, volume double precision)`, primary key `(symbol, timeframe, time)`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_migrations.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrations.py -v`
Expected: FAIL with `FileNotFoundError` for `004_candles_history.sql`.

- [ ] **Step 3: Write the migration**

`backend/db/migrations/004_candles_history.sql`:

```sql
-- Candle history for backtests.
--
-- Separate from ohlc_data, which the live scheduler trims to 30 days. This
-- table holds the depth a backtest needs (5m 6 months, 15m 1 year, 1h 3 years,
-- 1d all) and only closed bars. Applied idempotently at startup by
-- Database.bootstrap_schema().
CREATE TABLE IF NOT EXISTS candles_history (
    symbol     TEXT             NOT NULL,
    timeframe  TEXT             NOT NULL,
    time       TIMESTAMPTZ      NOT NULL,
    open       DOUBLE PRECISION NOT NULL,
    high       DOUBLE PRECISION NOT NULL,
    low        DOUBLE PRECISION NOT NULL,
    close      DOUBLE PRECISION NOT NULL,
    volume     DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (symbol, timeframe, time)
);

SELECT create_hypertable(
    'candles_history', 'time',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrations.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/db/migrations/004_candles_history.sql backend/tests/test_migrations.py
git commit -m "Add the candles_history hypertable for backtests

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: History constants and pure helpers

**Files:**
- Create: `backend/services/history_service.py`
- Test: `backend/tests/test_history_service.py`

**Interfaces:**
- Produces:
  - `PAIRS: Tuple[str, ...]`
  - `TIMEFRAME_MS: Dict[str, int]` — `{"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "1d": 86_400_000}`
  - `HISTORY_DEPTH_DAYS: Dict[str, Optional[int]]` — `{"5m": 183, "15m": 365, "1h": 1095, "1d": None}`
  - `depth_start_ms(timeframe: str, now_ms: int) -> int` — earliest open time to keep; `0` when depth is `None`.
  - `parse_klines(rows: list, now_ms: int) -> List[Dict[str, float|int]]` — closed bars only, candle shape.
  - `missing_bars(first_ms: int, last_ms: int, bars: int, timeframe: str) -> int`
  - `class UnknownHistoryTimeframe(ValueError)`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_history_service.py`:

```python
"""History store: depths, parsing, gap counting, paging, resume, retry."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import history_service as hs

DAY = 86_400_000
NOW = 1_780_000_000_000  # fixed "now" for every test


def kline(open_ms, step_ms, price=100.0):
    """A Binance kline row: strings for prices, close time = open + step - 1."""
    return [
        open_ms, str(price), str(price + 2), str(price - 2), str(price + 1), "12.5",
        open_ms + step_ms - 1, "0", 0, "0", "0", "0",
    ]


def test_depths_match_the_spec():
    assert hs.HISTORY_DEPTH_DAYS == {"5m": 183, "15m": 365, "1h": 1095, "1d": None}
    assert set(hs.TIMEFRAME_MS) == set(hs.HISTORY_DEPTH_DAYS)
    assert len(hs.PAIRS) == 9


def test_depth_start_is_aligned_to_the_timeframe():
    start = hs.depth_start_ms("1h", NOW)
    assert start % hs.TIMEFRAME_MS["1h"] == 0
    assert NOW - start >= 1095 * DAY
    assert NOW - start < 1095 * DAY + hs.TIMEFRAME_MS["1h"]


def test_unlimited_depth_starts_at_zero():
    assert hs.depth_start_ms("1d", NOW) == 0


def test_unknown_timeframe_is_refused():
    with pytest.raises(hs.UnknownHistoryTimeframe):
        hs.depth_start_ms("1m", NOW)


def test_parse_klines_coerces_and_keeps_only_closed_bars():
    step = hs.TIMEFRAME_MS["1h"]
    last_open = NOW - (NOW % step)  # the bar still forming at NOW
    rows = [kline(last_open - step, step), kline(last_open, step)]
    candles = hs.parse_klines(rows, NOW)
    assert candles == [{
        "time": last_open - step, "open": 100.0, "high": 102.0, "low": 98.0,
        "close": 101.0, "volume": 12.5,
    }]


def test_missing_bars_counts_holes_between_first_and_last():
    step = hs.TIMEFRAME_MS["15m"]
    assert hs.missing_bars(0, 9 * step, 10, "15m") == 0
    assert hs.missing_bars(0, 9 * step, 7, "15m") == 3
    assert hs.missing_bars(0, 0, 0, "15m") == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_history_service.py -v`
Expected: FAIL at import with `ImportError: cannot import name 'history_service'`.

- [ ] **Step 3: Write the helpers**

`backend/services/history_service.py`:

```python
"""
Candle history for backtests: how deep, where from, and how it is kept current.

Kept apart from CandleService on purpose. CandleService serves the chart the
latest 1000 bars through Redis; this fills a table years deep, page by page,
and must survive Binance rate limits and restarts halfway through. The SQL
lives in repositories.history_repository; everything here is testable without
a database.
"""
from typing import Any, Dict, List, Optional, Tuple

PAIRS: Tuple[str, ...] = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "DOTUSDT", "AVAXUSDT",
)

TIMEFRAME_MS: Dict[str, int] = {
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}

# How far back each timeframe is kept. Sized so the slowest replay (patterns)
# stays under ~30 minutes on the production e2-small; None keeps everything
# Binance has.
HISTORY_DEPTH_DAYS: Dict[str, Optional[int]] = {
    "5m": 183,
    "15m": 365,
    "1h": 1095,
    "1d": None,
}

DAY_MS = 24 * 60 * 60_000


class UnknownHistoryTimeframe(ValueError):
    """A timeframe the history store does not keep."""


def _step(timeframe: str) -> int:
    try:
        return TIMEFRAME_MS[timeframe]
    except KeyError:
        raise UnknownHistoryTimeframe(
            f"No history is kept for '{timeframe}'. Expected one of: {', '.join(TIMEFRAME_MS)}"
        )


def depth_start_ms(timeframe: str, now_ms: int) -> int:
    """The earliest bar open time to keep, aligned to the timeframe."""
    step = _step(timeframe)
    days = HISTORY_DEPTH_DAYS[timeframe]
    if days is None:
        return 0
    start = now_ms - days * DAY_MS
    return start - (start % step)


def parse_klines(rows: List[List[Any]], now_ms: int) -> List[Dict[str, Any]]:
    """
    Binance kline rows to candles, dropping the bar still forming.

    A bar is closed when its close time (row[6]) is before now. Storing a
    forming bar would bake a price that later changes into history a backtest
    trusts.
    """
    return [
        {
            "time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
        for row in rows
        if int(row[6]) < now_ms
    ]


def missing_bars(first_ms: int, last_ms: int, bars: int, timeframe: str) -> int:
    """Bars that should exist between first and last inclusive but do not."""
    if bars == 0:
        return 0
    expected = (last_ms - first_ms) // _step(timeframe) + 1
    return max(0, expected - bars)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_history_service.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/history_service.py backend/tests/test_history_service.py
git commit -m "History depths, kline parsing and gap counting

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: The history repository

**Files:**
- Create: `backend/repositories/history_repository.py`
- Test: `backend/tests/test_history_service.py` (append)

**Interfaces:**
- Consumes: `models.database.db` (`execute`, `fetch`, `fetchrow`, `pool`).
- Produces (`class HistoryRepository`, all `@staticmethod async`):
  - `upsert(symbol: str, timeframe: str, candles: List[Dict]) -> int` — rows written.
  - `latest_time(symbol: str, timeframe: str) -> Optional[int]` — newest open time ms, or None.
  - `load(symbol: str, timeframe: str, start_ms: int = 0, end_ms: Optional[int] = None) -> List[Dict]` — candle shape, oldest first.
  - `trim(symbol: str, timeframe: str, before_ms: int) -> None`
  - `coverage() -> List[Dict]` — `{symbol, timeframe, first: int ms, last: int ms, bars: int}` per stored series.
- Pure helpers (tested): `to_row(symbol, timeframe, candle) -> tuple`, `from_record(record: Dict) -> Dict`, `ms_to_dt(ms) -> datetime`, `dt_to_ms(dt) -> int`.

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_history_service.py`)

```python
from datetime import datetime, timezone

from repositories import history_repository as hr


def test_row_round_trip_keeps_ms_and_utc():
    candle = {"time": 1_700_000_000_000, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 9.0}
    row = hr.to_row("btcusdt", "1h", candle)
    assert row[0] == "BTCUSDT" and row[1] == "1h"
    assert row[2] == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
    record = {"time": row[2], "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 9.0}
    assert hr.from_record(record) == candle


def test_ms_conversion_is_exact_for_whole_seconds():
    assert hr.dt_to_ms(hr.ms_to_dt(1_780_000_000_000)) == 1_780_000_000_000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_history_service.py -v`
Expected: FAIL at import: `cannot import name 'history_repository'`.

- [ ] **Step 3: Write the repository**

`backend/repositories/history_repository.py`:

```python
"""
SQL for candles_history.

Times cross this boundary as unix milliseconds and are stored as timestamptz in
UTC. Nothing outside this file sees a datetime for a candle.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from models.database import db


def ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def dt_to_ms(dt: datetime) -> int:
    return int(round(dt.timestamp() * 1000))


def to_row(symbol: str, timeframe: str, candle: Dict[str, Any]) -> Tuple:
    return (
        symbol.upper(),
        timeframe,
        ms_to_dt(int(candle["time"])),
        float(candle["open"]),
        float(candle["high"]),
        float(candle["low"]),
        float(candle["close"]),
        float(candle["volume"]),
    )


def from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "time": dt_to_ms(record["time"]),
        "open": float(record["open"]),
        "high": float(record["high"]),
        "low": float(record["low"]),
        "close": float(record["close"]),
        "volume": float(record["volume"]),
    }


class HistoryRepository:
    @staticmethod
    async def upsert(symbol: str, timeframe: str, candles: List[Dict[str, Any]]) -> int:
        if not candles:
            return 0
        query = """
            INSERT INTO candles_history (symbol, timeframe, time, open, high, low, close, volume)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (symbol, timeframe, time) DO UPDATE
            SET open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                close = EXCLUDED.close, volume = EXCLUDED.volume
        """
        async with db.pool.acquire() as conn:
            await conn.executemany(query, [to_row(symbol, timeframe, c) for c in candles])
        return len(candles)

    @staticmethod
    async def latest_time(symbol: str, timeframe: str) -> Optional[int]:
        row = await db.fetchrow(
            "SELECT max(time) AS t FROM candles_history WHERE symbol = $1 AND timeframe = $2",
            symbol.upper(),
            timeframe,
        )
        return dt_to_ms(row["t"]) if row and row["t"] is not None else None

    @staticmethod
    async def load(
        symbol: str,
        timeframe: str,
        start_ms: int = 0,
        end_ms: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        args: List[Any] = [symbol.upper(), timeframe, ms_to_dt(start_ms)]
        clause = ""
        if end_ms is not None:
            args.append(ms_to_dt(end_ms))
            clause = "AND time <= $4"
        rows = await db.fetch(
            f"""
            SELECT time, open, high, low, close, volume FROM candles_history
            WHERE symbol = $1 AND timeframe = $2 AND time >= $3 {clause}
            ORDER BY time ASC
            """,
            *args,
        )
        return [from_record(r) for r in rows]

    @staticmethod
    async def trim(symbol: str, timeframe: str, before_ms: int) -> None:
        await db.execute(
            "DELETE FROM candles_history WHERE symbol = $1 AND timeframe = $2 AND time < $3",
            symbol.upper(),
            timeframe,
            ms_to_dt(before_ms),
        )

    @staticmethod
    async def coverage() -> List[Dict[str, Any]]:
        rows = await db.fetch(
            """
            SELECT symbol, timeframe, min(time) AS first, max(time) AS last, count(*) AS bars
            FROM candles_history
            GROUP BY symbol, timeframe
            ORDER BY symbol, timeframe
            """
        )
        return [
            {
                "symbol": r["symbol"],
                "timeframe": r["timeframe"],
                "first": dt_to_ms(r["first"]),
                "last": dt_to_ms(r["last"]),
                "bars": int(r["bars"]),
            }
            for r in rows
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_history_service.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/repositories/history_repository.py backend/tests/test_history_service.py
git commit -m "SQL for candles_history, with times as unix ms at the boundary

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Retrying Binance page fetch

**Files:**
- Modify: `backend/services/history_service.py`
- Test: `backend/tests/test_history_service.py` (append)

**Interfaces:**
- Consumes: `parse_klines`, `TIMEFRAME_MS`.
- Produces:
  - `BINANCE_KLINES = "https://api.binance.com/api/v3/klines"`, `PAGE_LIMIT = 1000`, `MAX_ATTEMPTS = 5`
  - `class HistoryFetchError(RuntimeError)`
  - `async fetch_page(client, symbol: str, timeframe: str, start_ms: int, *, now_ms: int, sleep=asyncio.sleep) -> List[Dict]` — closed candles with `time >= start_ms`, at most 1000. `client` is any object with `async get(url, params=...) -> httpx.Response`.

- [ ] **Step 1: Write the failing tests** (append)

```python
import httpx


class StubClient:
    """Replays a list of (status, json, headers) responses and records params."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def get(self, url, params=None):
        self.calls.append(params)
        status, body, headers = self.responses.pop(0)
        return httpx.Response(status, json=body, headers=headers, request=httpx.Request("GET", url))


async def no_sleep(_seconds):
    no_sleep.slept.append(_seconds)


no_sleep.slept = []


async def test_fetch_page_requests_the_right_window_and_parses():
    step = hs.TIMEFRAME_MS["1h"]
    start = NOW - 10 * step - (NOW % step)
    client = StubClient([(200, [kline(start, step)], {})])
    candles = await hs.fetch_page(client, "btcusdt", "1h", start, now_ms=NOW, sleep=no_sleep)
    assert client.calls == [{"symbol": "BTCUSDT", "interval": "1h", "startTime": start, "limit": 1000}]
    assert [c["time"] for c in candles] == [start]


async def test_fetch_page_honours_retry_after_on_429():
    no_sleep.slept.clear()
    step = hs.TIMEFRAME_MS["1h"]
    start = NOW - 10 * step - (NOW % step)
    client = StubClient([
        (429, {"code": -1003}, {"Retry-After": "7"}),
        (200, [kline(start, step)], {}),
    ])
    candles = await hs.fetch_page(client, "BTCUSDT", "1h", start, now_ms=NOW, sleep=no_sleep)
    assert len(candles) == 1
    assert no_sleep.slept == [7.0]


async def test_fetch_page_backs_off_on_5xx_then_gives_up():
    no_sleep.slept.clear()
    client = StubClient([(502, {}, {})] * hs.MAX_ATTEMPTS)
    with pytest.raises(hs.HistoryFetchError):
        await hs.fetch_page(client, "BTCUSDT", "1h", 0, now_ms=NOW, sleep=no_sleep)
    assert len(client.calls) == hs.MAX_ATTEMPTS
    assert no_sleep.slept == sorted(no_sleep.slept) and no_sleep.slept[0] >= 1


async def test_fetch_page_does_not_retry_a_bad_request():
    client = StubClient([(400, {"code": -1121, "msg": "Invalid symbol."}, {})])
    with pytest.raises(hs.HistoryFetchError, match="400"):
        await hs.fetch_page(client, "NOPE", "1h", 0, now_ms=NOW, sleep=no_sleep)
    assert len(client.calls) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_history_service.py -v`
Expected: the 4 new tests FAIL with `AttributeError: module 'services.history_service' has no attribute 'fetch_page'`.

- [ ] **Step 3: Implement** (append to `backend/services/history_service.py`; add `import asyncio` and `import httpx` to the imports at the top)

```python
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
PAGE_LIMIT = 1000
MAX_ATTEMPTS = 5
# Binance uses 418 once an IP has ignored 429s; both carry Retry-After.
RATE_LIMITED = (418, 429)


class HistoryFetchError(RuntimeError):
    """A page could not be fetched after retries, or the request was invalid."""


async def fetch_page(
    client: Any,
    symbol: str,
    timeframe: str,
    start_ms: int,
    *,
    now_ms: int,
    sleep=asyncio.sleep,
) -> List[Dict[str, Any]]:
    """
    One page of up to 1000 closed candles starting at start_ms.

    Rate limits wait for as long as Binance asks. Server errors and network
    failures back off exponentially. A 4xx other than a rate limit means the
    request itself is wrong, so retrying would only burn weight.
    """
    params = {
        "symbol": symbol.upper(),
        "interval": timeframe,
        "startTime": start_ms,
        "limit": PAGE_LIMIT,
    }
    last_error = "no attempt made"
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = await client.get(BINANCE_KLINES, params=params)
        except httpx.HTTPError as exc:
            last_error = f"network error: {exc}"
            await sleep(float(2 ** attempt))
            continue

        if response.status_code == 200:
            rows = response.json()
            if not isinstance(rows, list):
                raise HistoryFetchError(f"Unexpected kline response for {symbol} {timeframe}")
            return parse_klines(rows, now_ms)

        if response.status_code in RATE_LIMITED:
            last_error = f"rate limited ({response.status_code})"
            await sleep(float(response.headers.get("Retry-After", 60)))
            continue

        if response.status_code >= 500:
            last_error = f"server error {response.status_code}"
            await sleep(float(2 ** attempt))
            continue

        raise HistoryFetchError(
            f"Binance refused {symbol} {timeframe} ({response.status_code}): {response.text[:200]}"
        )

    raise HistoryFetchError(
        f"Gave up on {symbol} {timeframe} from {start_ms} after {MAX_ATTEMPTS} attempts: {last_error}"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_history_service.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/history_service.py backend/tests/test_history_service.py
git commit -m "Fetch history pages from Binance with rate-limit-aware retries

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: `backfill` — resume, page, trim

**Files:**
- Modify: `backend/services/history_service.py`
- Test: `backend/tests/test_history_service.py` (append)

**Interfaces:**
- Consumes: `fetch_page`, `depth_start_ms`, `TIMEFRAME_MS`, `HistoryRepository` (`latest_time`, `upsert`, `trim`).
- Produces:
  - `@dataclass BackfillResult(symbol: str, timeframe: str, pages: int, bars: int, error: Optional[str] = None)`
  - `PAGE_PAUSE_SECONDS = 0.3`
  - `async backfill(symbol: str, timeframe: str, *, client, now_ms: int, repo=HistoryRepository, fetch=fetch_page, sleep=asyncio.sleep) -> BackfillResult`

Behaviour: start at `max(depth_start, latest + step)` (or `depth_start` when empty); fetch pages, upsert each immediately (so a crash loses at most one page); stop on an empty page, on a page whose newest bar is the newest closed bar (`>= now - 2*step`), or when a page does not advance; pause between pages; finally `trim(before=depth_start)` when depth is limited.

- [ ] **Step 1: Write the failing tests** (append)

```python
class FakeRepo:
    def __init__(self, latest=None):
        self.latest = latest
        self.rows = {}
        self.trimmed = None

    async def latest_time(self, symbol, timeframe):
        return self.latest

    async def upsert(self, symbol, timeframe, candles):
        for c in candles:
            self.rows[c["time"]] = c
        return len(candles)

    async def trim(self, symbol, timeframe, before_ms):
        self.trimmed = before_ms
        self.rows = {t: c for t, c in self.rows.items() if t >= before_ms}


def fake_exchange(first_ms, step, now_ms, page=1000):
    """A fetch function serving contiguous bars from first_ms up to the last closed bar."""
    calls = []

    async def fetch(client, symbol, timeframe, start_ms, *, now_ms=now_ms, sleep=None):
        calls.append(start_ms)
        t = max(start_ms, first_ms)
        t += (-t) % step
        out = []
        while len(out) < page and t + step <= now_ms:
            out.append({"time": t, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
            t += step
        return out

    return fetch, calls


async def test_backfill_from_empty_assembles_contiguous_history():
    step = hs.TIMEFRAME_MS["1h"]
    start = hs.depth_start_ms("1h", NOW)
    fetch, calls = fake_exchange(start, step, NOW)
    repo = FakeRepo()
    result = await hs.backfill("BTCUSDT", "1h", client=None, now_ms=NOW, repo=repo, fetch=fetch, sleep=no_sleep)
    times = sorted(repo.rows)
    assert times[0] == start
    assert all(b - a == step for a, b in zip(times, times[1:]))
    assert times[-1] + step <= NOW
    assert result.bars == len(times) and result.pages == len(calls) and result.error is None
    assert calls[0] == start


async def test_backfill_resumes_after_the_newest_stored_bar():
    step = hs.TIMEFRAME_MS["1h"]
    last_closed_open = NOW - (NOW % step) - step
    stored = last_closed_open - 5 * step
    fetch, calls = fake_exchange(0, step, NOW)
    repo = FakeRepo(latest=stored)
    result = await hs.backfill("BTCUSDT", "1h", client=None, now_ms=NOW, repo=repo, fetch=fetch, sleep=no_sleep)
    assert calls == [stored + step]
    assert result.bars == 5


async def test_backfill_trims_below_the_depth():
    step = hs.TIMEFRAME_MS["5m"]
    fetch, _ = fake_exchange(0, step, NOW)
    repo = FakeRepo(latest=NOW - (NOW % step) - 2 * step)
    await hs.backfill("BTCUSDT", "5m", client=None, now_ms=NOW, repo=repo, fetch=fetch, sleep=no_sleep)
    assert repo.trimmed == hs.depth_start_ms("5m", NOW)


async def test_backfill_keeps_everything_for_daily():
    step = hs.TIMEFRAME_MS["1d"]
    fetch, calls = fake_exchange(1_500_000_000_000 - (1_500_000_000_000 % step), step, NOW)
    repo = FakeRepo()
    await hs.backfill("BTCUSDT", "1d", client=None, now_ms=NOW, repo=repo, fetch=fetch, sleep=no_sleep)
    assert calls[0] == 0
    assert repo.trimmed is None


async def test_backfill_keeps_pages_already_stored_when_a_later_page_fails():
    step = hs.TIMEFRAME_MS["1h"]
    good, _ = fake_exchange(hs.depth_start_ms("1h", NOW), step, NOW)
    pages = {"n": 0}

    async def flaky(client, symbol, timeframe, start_ms, *, now_ms, sleep=None):
        pages["n"] += 1
        if pages["n"] == 2:
            raise hs.HistoryFetchError("boom")
        return await good(client, symbol, timeframe, start_ms, now_ms=now_ms)

    repo = FakeRepo()
    result = await hs.backfill("BTCUSDT", "1h", client=None, now_ms=NOW, repo=repo, fetch=flaky, sleep=no_sleep)
    assert result.error == "boom"
    assert result.bars == 1000 and len(repo.rows) == 1000


async def test_backfill_stops_when_a_page_does_not_advance():
    step = hs.TIMEFRAME_MS["1h"]
    start = hs.depth_start_ms("1h", NOW)

    async def stuck(client, symbol, timeframe, start_ms, *, now_ms, sleep=None):
        stuck.calls += 1
        return [{"time": start, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}]

    stuck.calls = 0
    await hs.backfill("BTCUSDT", "1h", client=None, now_ms=NOW, repo=FakeRepo(), fetch=stuck, sleep=no_sleep)
    assert stuck.calls == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_history_service.py -v`
Expected: the 6 new tests FAIL with `AttributeError: ... has no attribute 'backfill'`.

- [ ] **Step 3: Implement** (append to `backend/services/history_service.py`; add `from dataclasses import dataclass` to the imports)

```python
PAGE_PAUSE_SECONDS = 0.3


@dataclass
class BackfillResult:
    symbol: str
    timeframe: str
    pages: int
    bars: int
    error: Optional[str] = None


def _default_repo():
    # Imported lazily so the pure helpers above import without a database.
    from repositories.history_repository import HistoryRepository

    return HistoryRepository


async def backfill(
    symbol: str,
    timeframe: str,
    *,
    client: Any,
    now_ms: int,
    repo: Any = None,
    fetch=None,
    sleep=asyncio.sleep,
) -> BackfillResult:
    """
    Bring one series up to the newest closed bar, then trim past its depth.

    Resumes after the newest stored bar, so a restart repeats nothing. Each page
    is stored as soon as it arrives: a failure part-way keeps every earlier page
    and reports the error instead of raising, so one bad pair cannot stop the
    others.
    """
    repo = repo or _default_repo()
    fetch = fetch or fetch_page
    step = _step(timeframe)
    floor = depth_start_ms(timeframe, now_ms)

    latest = await repo.latest_time(symbol, timeframe)
    cursor = floor if latest is None else max(floor, latest + step)
    newest_closed = now_ms - (now_ms % step) - step

    pages = 0
    bars = 0
    error: Optional[str] = None
    while cursor <= newest_closed:
        try:
            candles = await fetch(client, symbol, timeframe, cursor, now_ms=now_ms, sleep=sleep)
        except HistoryFetchError as exc:
            error = str(exc)
            break
        pages += 1
        if not candles:
            break
        bars += await repo.upsert(symbol, timeframe, candles)
        advanced_to = candles[-1]["time"] + step
        if advanced_to <= cursor:
            break  # the exchange handed back what we already asked past
        cursor = advanced_to
        if cursor <= newest_closed:
            await sleep(PAGE_PAUSE_SECONDS)

    if HISTORY_DEPTH_DAYS[timeframe] is not None:
        await repo.trim(symbol, timeframe, floor)

    return BackfillResult(symbol.upper(), timeframe, pages, bars, error)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_history_service.py -v`
Expected: 18 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/history_service.py backend/tests/test_history_service.py
git commit -m "Backfill history resumably, page by page, trimmed to depth

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: `topup_all` across every pair and timeframe

**Files:**
- Modify: `backend/services/history_service.py`
- Test: `backend/tests/test_history_service.py` (append)

**Interfaces:**
- Consumes: `backfill`, `PAIRS`, `TIMEFRAME_MS`.
- Produces: `async topup_all(*, client, now_ms: Optional[int] = None, pairs=PAIRS, timeframes=tuple(TIMEFRAME_MS), run=backfill) -> List[BackfillResult]` — sequential (one series at a time, to stay light on the e2-small and on Binance weight); a series that raises anything is recorded with `error` and the rest continue.

- [ ] **Step 1: Write the failing test** (append)

```python
async def test_topup_all_continues_past_a_failing_series():
    seen = []

    async def run(symbol, timeframe, *, client, now_ms):
        seen.append((symbol, timeframe))
        if symbol == "ETHUSDT" and timeframe == "15m":
            raise RuntimeError("db went away")
        return hs.BackfillResult(symbol, timeframe, pages=1, bars=3)

    results = await hs.topup_all(
        client=None, now_ms=NOW, pairs=("BTCUSDT", "ETHUSDT"), timeframes=("15m", "1h"), run=run
    )
    assert seen == [("BTCUSDT", "15m"), ("BTCUSDT", "1h"), ("ETHUSDT", "15m"), ("ETHUSDT", "1h")]
    failed = [r for r in results if r.error]
    assert len(failed) == 1 and "db went away" in failed[0].error
    assert sum(r.bars for r in results) == 9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_history_service.py::test_topup_all_continues_past_a_failing_series -v`
Expected: FAIL with `AttributeError: ... has no attribute 'topup_all'`.

- [ ] **Step 3: Implement** (append; add `import time` to the imports)

```python
async def topup_all(
    *,
    client: Any,
    now_ms: Optional[int] = None,
    pairs: Tuple[str, ...] = PAIRS,
    timeframes: Tuple[str, ...] = tuple(TIMEFRAME_MS),
    run=None,
) -> List[BackfillResult]:
    """
    Every pair and timeframe, one series at a time.

    Sequential on purpose: the worker shares a small VM and an IP's Binance
    weight with the live API. The first run on an empty table is the full
    backfill (minutes); every run after that fetches about one page per series.
    """
    run = run or backfill
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    results: List[BackfillResult] = []
    for symbol in pairs:
        for timeframe in timeframes:
            try:
                results.append(await run(symbol, timeframe, client=client, now_ms=now_ms))
            except Exception as exc:  # one broken series must not stop the rest
                results.append(BackfillResult(symbol, timeframe, 0, 0, error=str(exc)))
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_history_service.py -v`
Expected: 19 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/history_service.py backend/tests/test_history_service.py
git commit -m "Top up every pair and timeframe, isolating failures

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: `GET /api/history/coverage`

**Files:**
- Create: `backend/controllers/history_controller.py`
- Modify: `backend/controllers/__init__.py`, `backend/main.py:7-13` and `:143-149`, `backend/tests/test_app_imports.py`
- Test: `backend/tests/test_history_controller.py`

**Interfaces:**
- Consumes: `HistoryRepository.coverage()`, `missing_bars`, `HISTORY_DEPTH_DAYS`, `cache_service.get/set`.
- Produces: `router` with `GET /api/history/coverage` → `{"depth_days": {tf: days|None}, "series": [{symbol, timeframe, first, last, bars, gaps}]}`; `COVERAGE_CACHE_SECONDS = 60`; cache key `history:coverage`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_history_controller.py`:

```python
"""Coverage: what history exists, with gaps counted, cached briefly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controllers import history_controller as hc

H = 3_600_000


class FakeCache:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, expiration=None):
        self.store[key] = value
        return True


async def test_coverage_counts_gaps_and_caches(monkeypatch):
    calls = []

    async def coverage():
        calls.append(1)
        return [{"symbol": "BTCUSDT", "timeframe": "1h", "first": 0, "last": 9 * H, "bars": 8}]

    cache = FakeCache()
    monkeypatch.setattr(hc.HistoryRepository, "coverage", staticmethod(coverage))
    monkeypatch.setattr(hc, "cache_service", cache)

    body = await hc.get_coverage()
    assert body["series"] == [
        {"symbol": "BTCUSDT", "timeframe": "1h", "first": 0, "last": 9 * H, "bars": 8, "gaps": 2}
    ]
    assert body["depth_days"]["1h"] == 1095 and body["depth_days"]["1d"] is None

    again = await hc.get_coverage()
    assert again == body and len(calls) == 1
```

Also add `"controllers.history_controller",` to the `CONTROLLERS` list in `backend/tests/test_app_imports.py` (keep it alphabetical: after `"controllers.chat_controller",`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_history_controller.py tests/test_app_imports.py -v`
Expected: FAIL with `ImportError: cannot import name 'history_controller'`.

- [ ] **Step 3: Implement**

`backend/controllers/history_controller.py`:

```python
"""
What candle history exists for backtests.

Public: it describes market data, not anyone's rules. The UI reads it so it
never offers a backtest over history that is not there.
"""
from typing import Any, Dict

from fastapi import APIRouter

from repositories.history_repository import HistoryRepository
from services.cache_service import cache_service
from services.history_service import HISTORY_DEPTH_DAYS, missing_bars

router = APIRouter(prefix="/api/history", tags=["History"])

COVERAGE_CACHE_SECONDS = 60
CACHE_KEY = "history:coverage"


@router.get("/coverage")
async def get_coverage() -> Dict[str, Any]:
    cached = await cache_service.get(CACHE_KEY)
    if isinstance(cached, dict):
        return cached

    series = [
        {**s, "gaps": missing_bars(s["first"], s["last"], s["bars"], s["timeframe"])}
        for s in await HistoryRepository.coverage()
        if s["timeframe"] in HISTORY_DEPTH_DAYS
    ]
    body = {"depth_days": dict(HISTORY_DEPTH_DAYS), "series": series}
    await cache_service.set(CACHE_KEY, body, COVERAGE_CACHE_SECONDS)
    return body
```

`backend/controllers/__init__.py` — add the import and export:

```python
from .strategy_controller import router as strategy_router
from .ohlc_controller import router as ohlc_router
from .websocket_controller import router as websocket_router
from .rules_controller import router as rules_router
from .auth_controller import router as auth_router
from .history_controller import router as history_router

__all__ = [
    "strategy_router",
    "ohlc_router",
    "websocket_router",
    "rules_router",
    "auth_router",
    "history_router",
]
```

`backend/main.py` — add `history_router,` to the `from controllers import (...)` block, and after `app.include_router(auth_router)` add:

```python
app.include_router(history_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_history_controller.py tests/test_app_imports.py -v`
Expected: all passed (1 + 8).

- [ ] **Step 5: Commit**

```bash
git add backend/controllers/history_controller.py backend/controllers/__init__.py backend/main.py backend/tests/test_history_controller.py backend/tests/test_app_imports.py
git commit -m "Report candle history coverage, gaps counted

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: The worker process and backfill CLI

**Files:**
- Create: `backend/worker.py`, `backend/scripts/__init__.py` (empty), `backend/scripts/backfill_history.py`
- Test: `backend/tests/test_worker.py`

**Interfaces:**
- Consumes: `topup_all`, `backfill`, `BackfillResult`, `db.connect/bootstrap_schema/disconnect`, `candle_service._http` (shared httpx client) and `close_http`.
- Produces:
  - `worker.HEARTBEAT_PATH = Path("/tmp/worker-heartbeat")`, `worker.TOPUP_JOB_ID = "history_topup"`
  - `worker.beat(path: Path = HEARTBEAT_PATH) -> None` — touches the file.
  - `worker.summarise(results: List[BackfillResult]) -> str` — one log line.
  - `worker.build_scheduler(topup, heartbeat) -> AsyncIOScheduler` — hourly `topup` (id `history_topup`, `next_run_time` now, `max_instances=1`, `coalesce=True`) and a 60 s `heartbeat`.
  - `async worker.main() -> None`
  - Slices 2–4 add the job loop to `worker.main()`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_worker.py`:

```python
"""The worker: schedule shape, heartbeat, and a readable summary."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import worker
from services.history_service import BackfillResult


async def test_scheduler_runs_topup_hourly_now_and_never_overlapping():
    async def topup():
        pass

    def heartbeat():
        pass

    scheduler = worker.build_scheduler(topup, heartbeat)
    job = scheduler.get_job(worker.TOPUP_JOB_ID)
    assert job.trigger.interval.total_seconds() == 3600
    assert job.max_instances == 1 and job.coalesce is True
    assert job.next_run_time is not None
    beat = scheduler.get_job("heartbeat")
    assert beat.trigger.interval.total_seconds() == 60


def test_beat_touches_the_heartbeat_file(tmp_path):
    path = tmp_path / "hb"
    worker.beat(path)
    first = path.stat().st_mtime
    worker.beat(path)
    assert path.exists() and path.stat().st_mtime >= first


def test_summary_counts_bars_and_names_failures():
    line = worker.summarise([
        BackfillResult("BTCUSDT", "1h", pages=2, bars=1500),
        BackfillResult("ETHUSDT", "5m", pages=0, bars=0, error="rate limited (429)"),
    ])
    assert "1500 bars" in line and "2 series" in line
    assert "ETHUSDT 5m: rate limited (429)" in line
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_worker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'worker'`.

- [ ] **Step 3: Implement**

`backend/worker.py`:

```python
"""
The backtest worker process.

Runs beside the API in its own container, at a lower CPU share, so nothing it
does can delay a live alert. Slice 1 gives it one duty: keep candles_history
current. Later slices add the backtest job loop here.

    python worker.py
"""
import asyncio
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from models.database import db
from services.candle_service import _http, close_http
from services.history_service import BackfillResult, topup_all

HEARTBEAT_PATH = Path("/tmp/worker-heartbeat")
TOPUP_JOB_ID = "history_topup"


def beat(path: Path = HEARTBEAT_PATH) -> None:
    """Touched every minute; the container healthcheck reads its age."""
    path.touch()


def summarise(results: List[BackfillResult]) -> str:
    bars = sum(r.bars for r in results)
    failures = [f"{r.symbol} {r.timeframe}: {r.error}" for r in results if r.error]
    line = f"[history] {bars} bars across {len(results)} series"
    if failures:
        line += "; failed: " + "; ".join(failures)
    return line


def build_scheduler(topup, heartbeat) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        topup,
        trigger=IntervalTrigger(hours=1),
        id=TOPUP_JOB_ID,
        next_run_time=datetime.now(timezone.utc),
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        heartbeat,
        trigger=IntervalTrigger(seconds=60),
        id="heartbeat",
        next_run_time=datetime.now(timezone.utc),
        replace_existing=True,
    )
    return scheduler


async def _topup() -> None:
    client = await _http()
    print(summarise(await topup_all(client=client)), flush=True)


async def main() -> None:
    await db.connect()
    await db.bootstrap_schema()
    print("[worker] connected; schema up to date", flush=True)

    scheduler = build_scheduler(_topup, beat)
    scheduler.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows development machines
            pass
    await stop.wait()

    scheduler.shutdown(wait=False)
    await close_http()
    await db.disconnect()
    print("[worker] stopped", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
```

`backend/scripts/__init__.py`: empty file.

`backend/scripts/backfill_history.py`:

```python
"""
Fill or top up candle history by hand.

    python -m scripts.backfill_history                      # everything
    python -m scripts.backfill_history --symbol BTCUSDT --timeframe 1h

The worker does the same thing hourly; this is for the first fill on a new
machine and for repairing one series without waiting.
"""
import argparse
import asyncio

from models.database import db
from services.candle_service import _http, close_http
from services.history_service import PAIRS, TIMEFRAME_MS, topup_all
from worker import summarise


async def run(symbols, timeframes) -> None:
    await db.connect()
    await db.bootstrap_schema()
    try:
        client = await _http()
        results = await topup_all(client=client, pairs=tuple(symbols), timeframes=tuple(timeframes))
        for r in results:
            print(f"{r.symbol:9} {r.timeframe:4} pages={r.pages:4} bars={r.bars:7} {r.error or ''}")
        print(summarise(results))
    finally:
        await close_http()
        await db.disconnect()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", choices=PAIRS, action="append")
    parser.add_argument("--timeframe", choices=tuple(TIMEFRAME_MS), action="append")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run(args.symbol or PAIRS, args.timeframe or tuple(TIMEFRAME_MS)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_worker.py -v`
Expected: 3 passed.

Then the whole suite: `.venv/Scripts/python.exe -m pytest -q`
Expected: **334 passed**, 0 failed — 308 baseline + 2 migrations + 19 history service + 1 coverage + 1 new app-import case + 3 worker.

- [ ] **Step 5: Commit**

```bash
git add backend/worker.py backend/scripts/__init__.py backend/scripts/backfill_history.py backend/tests/test_worker.py
git commit -m "Worker process that keeps candle history current, and a backfill CLI

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: The `backtester` compose service

**Files:**
- Modify: `docker-compose.prod.yml`

**Interfaces:**
- Consumes: `backend/worker.py`, `HEARTBEAT_PATH=/tmp/worker-heartbeat`.
- Produces: service `backtester` (container `tradesmart-backtester`) — same build as `backend`, `command: python worker.py`, `cpu_shares: 256`, `mem_limit: 512m`, heartbeat healthcheck, no published ports.

- [ ] **Step 1: Share backend's environment through a YAML anchor**

In `docker-compose.prod.yml`, change the `backend` service's `environment:` line to `environment: &backend-env` (the mapping beneath it is unchanged).

- [ ] **Step 2: Add the service** after the `backend` service and before `caddy`:

```yaml
  # Backtest worker: keeps candle history current (slice 1) and later runs
  # backtest jobs. Same image as the API, a quarter of its CPU weight, so a
  # long replay can never delay the live alert sweep. No ports.
  backtester:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: tradesmart-backtester
    command: ["python", "worker.py"]
    environment: *backend-env
    cpu_shares: 256
    mem_limit: 512m
    healthcheck:
      # The image's healthcheck probes the API port, which the worker does not
      # serve. The worker touches this file every minute instead.
      test: ["CMD", "python", "-c", "import os,sys,time; sys.exit(0 if time.time() - os.path.getmtime('/tmp/worker-heartbeat') < 180 else 1)"]
      interval: 60s
      timeout: 10s
      start_period: 120s
      retries: 3
    depends_on:
      timescaledb:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - tradesmart-network
    restart: unless-stopped
```

- [ ] **Step 3: Validate the file**

Run (from repo root, any machine with Docker; placeholders only satisfy the `:?` checks):

```bash
LLM_API_KEY=x TIMESCALE_PASSWORD=x JWT_SECRET=x API_DOMAIN=x docker compose -f docker-compose.prod.yml config --services
```

Expected: `timescaledb`, `redis`, `backend`, `backtester`, `caddy` (any order), exit 0. If Docker is not available locally, run it on the VM in Task 10 before `up`.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.prod.yml
git commit -m "Run the backtest worker as its own low-priority container

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Ship and verify on production

**Files:** none (operations). Prod VM: `gcloud compute ssh varun@tradesmart-backend --zone asia-south1-a`, app at `/opt/tradesmart/app`, compose file `docker-compose.prod.yml`.

- [ ] **Step 1: Full suite green, secret scan, PR, merge**

```bash
cd backend && .venv/Scripts/python.exe -m pytest -q   # 0 failures
cd .. && git diff main --name-only
git diff main | grep -E "^\+" | grep -iE "csk-|gsk_|JWT_SECRET=" ; echo "scan exit $? (1 = clean)"
git push -u origin feature/backtesting
gh pr create --base main --title "Backtesting slice 1: history store" --body "<summary + test counts>

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
gh pr merge --merge
git checkout main && git pull
```

- [ ] **Step 2: Deploy both containers**

```bash
gcloud compute ssh varun@tradesmart-backend --zone asia-south1-a --command '
cd /opt/tradesmart/app && sudo git pull --ff-only -q && sudo git log --oneline -1 &&
sudo docker compose -f docker-compose.prod.yml config --services &&
sudo docker compose -f docker-compose.prod.yml build -q backend backtester &&
sudo docker compose -f docker-compose.prod.yml up -d backend backtester 2>&1 | tail -2 &&
sleep 30 && sudo docker compose -f docker-compose.prod.yml ps --format "{{.Service}} {{.Status}}"'
```

Expected: `backend Up … (healthy)`, `backtester Up … (health: starting)` or `(healthy)`.

Both containers run `bootstrap_schema()` on boot, so on this first start they may race on `CREATE TABLE IF NOT EXISTS candles_history`. The loser logs a duplicate-object error: the backend logs it and carries on (its lifespan catches schema errors), and the worker exits and is restarted by `restart: unless-stopped`, finding the table on its second boot. If `docker logs tradesmart-backtester` shows exactly one such error followed by `[worker] connected; schema up to date`, that is this, not a fault.

- [ ] **Step 3: Watch the first fill complete**

```bash
gcloud compute ssh varun@tradesmart-backend --zone asia-south1-a --command '
sudo docker logs --since 30m tradesmart-backtester 2>&1 | tail -5'
```

Expected within ~15 minutes: `[worker] connected; schema up to date` and one `[history] N bars across 36 series` line with no `failed:` section. N ≈ 9 × (52,700 + 35,040 + 26,280 + ~3,000) ≈ 1.05 M. If `failed:` lists series, wait for the next hourly run (it resumes) or run `sudo docker exec tradesmart-backtester python -m scripts.backfill_history --symbol <S> --timeframe <TF>`.

- [ ] **Step 4: Verify coverage from outside**

```bash
curl -s https://api.vibetrading.club/api/history/coverage | node -e '
const d=JSON.parse(require("fs").readFileSync(0,"utf8"));
console.log("series", d.series.length);
for (const s of d.series) console.log(s.symbol, s.timeframe, new Date(s.first).toISOString().slice(0,10), "→", new Date(s.last).toISOString().slice(0,16), s.bars, "gaps", s.gaps);'
```

Expected: `series 36`; 5m first ≈ 183 days ago, 15m ≈ 1 year, 1h ≈ 3 years, 1d from the pair's listing (BTC 2017-08-17); `last` within one bar of now; `gaps` 0 or small (Binance has a few historical outages — record them, do not fill).

- [ ] **Step 5: Verify live alerts were not affected**

```bash
gcloud compute ssh varun@tradesmart-backend --zone asia-south1-a --command '
sudo docker logs --since 30m tradesmart-backend 2>&1 | grep -iE "rule sweep|error" | tail -5;
sudo docker stats --no-stream --format "{{.Name}} {{.CPUPerc}} {{.MemUsage}}"; df -h / | tail -1'
```

Expected: no `Strategy rule sweep failed` lines; backtester memory under 512 MiB; disk use increased by well under 1 GB.

- [ ] **Step 6: One hour later, confirm the top-up is incremental**

```bash
gcloud compute ssh varun@tradesmart-backend --zone asia-south1-a --command '
sudo docker logs --since 70m tradesmart-backtester 2>&1 | grep "\[history\]" | tail -2'
```

Expected: the second `[history]` line reports a few hundred bars (≈ 12 per 5m series + 4 per 15m + 1 per 1h), not a refill.
