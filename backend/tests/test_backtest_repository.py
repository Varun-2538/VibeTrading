"""Tape codec: compact, lossless, and small enough to store."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repositories.backtest_repository import ACTIVE_STATUSES, decode_tape, encode_tape


def test_tape_round_trips_exactly():
    rows = [[405, [["W:1:2:3:confirmed", "bullish", False, 71.5, None]]],
            [406, [["support:approach:99.5", "bullish", False, None, "strong"]]]]
    assert decode_tape(encode_tape(rows)) == rows


def test_tape_compresses_repetitive_rows():
    rows = [[i, [["W:1700000000000:1700003600000:1700007200000:confirmed", "bullish", False, 70.0, None]]]
            for i in range(20_000)]
    assert len(encode_tape(rows)) < 200_000


def test_active_statuses_are_the_running_ones():
    assert ACTIVE_STATUSES == ("queued", "replaying", "studying", "tuning")
