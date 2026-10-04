"""
The database helpers, against a fake pool - there is no Postgres in the test run.

What is worth pinning here is not SQL but sequencing: that the migrations are
applied on one connection under one lock and that the lock is always released,
and that a transaction is a real transaction rather than a pooled helper
pretending to be one. Three processes boot against the same database, so
"applied twice at once" is an ordinary Tuesday, not an edge case.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.database import BOOTSTRAP_LOCK, Database


class FakeTransaction:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.conn.calls.append(("begin",))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.conn.calls.append(("rollback" if exc_type else "commit",))
        return False


class FakeConn:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on
        self.released = False

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("duplicate key value violates unique constraint")
        return "OK"

    def transaction(self):
        return FakeTransaction(self)


class Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        self.conn.released = True
        return False


class FakePool:
    def __init__(self, conn):
        self.conn, self.acquisitions = conn, 0

    def acquire(self):
        self.acquisitions += 1
        return Acquire(self.conn)


def db_with(conn):
    database = Database()
    database.pool = FakePool(conn)
    return database


def sql_calls(conn):
    return [c[0] for c in conn.calls if isinstance(c[0], str)]


@pytest.mark.asyncio
async def test_migrations_apply_on_one_connection_under_one_lock():
    conn = FakeConn()
    database = db_with(conn)
    await database.bootstrap_schema()

    calls = sql_calls(conn)
    assert calls[0] == "SELECT pg_advisory_lock($1)"
    assert calls[-1] == "SELECT pg_advisory_unlock($1)"
    assert conn.calls[0][1] == (BOOTSTRAP_LOCK,) == conn.calls[-1][1]
    # One connection for the whole run: a lock held on a connection the loop
    # does not use would protect nothing.
    assert database.pool.acquisitions == 1
    # Every migration file, in name order, between the lock and the unlock.
    applied = calls[1:-1]
    files = sorted((Path(__file__).resolve().parents[1] / "db" / "migrations").glob("*.sql"))
    assert len(applied) == len(files) and files
    assert applied[0] == files[0].read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_a_failed_migration_still_releases_the_lock():
    """Otherwise one bad deploy wedges every other process at boot, forever."""
    conn = FakeConn(fail_on="CREATE TABLE")
    with pytest.raises(RuntimeError):
        await db_with(conn).bootstrap_schema()
    assert sql_calls(conn)[-1] == "SELECT pg_advisory_unlock($1)"


@pytest.mark.asyncio
async def test_a_transaction_commits_once_and_rolls_back_on_error():
    conn = FakeConn()
    database = db_with(conn)

    async with database.transaction() as tx:
        await tx.execute("INSERT INTO a VALUES (1)")
    assert [c[0] for c in conn.calls] == ["begin", "INSERT INTO a VALUES (1)", "commit"]
    assert conn.released

    conn = FakeConn()
    with pytest.raises(ValueError):
        async with db_with(conn).transaction() as tx:
            await tx.execute("INSERT INTO a VALUES (2)")
            raise ValueError("the caller changed its mind")
    assert [c[0] for c in conn.calls][-1] == "rollback"


def test_the_pool_is_sized_from_settings():
    """
    The API keeps the generous default; the background processes override it
    through the environment, because Postgres allows 100 connections in total
    and three processes asking for 20 each is most of it.
    """
    from config.settings import Settings

    assert Settings.model_fields["db_pool_min"].default == 5
    assert Settings.model_fields["db_pool_max"].default == 20
