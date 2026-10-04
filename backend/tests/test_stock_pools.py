"""
Robinhood Stock Tokens as a candle source, and what the assistant does with one.

The candles must arrive in exactly the shape Binance's do, or every detector reads a
stock differently from a crypto pair. The tokens must be the ones the vault trades,
or the chart beside the "trade in vault" button is of a different contract. And a
request to be alerted on a stock must be declined, because no rule can watch one.
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controllers import chat_controller as cc
from models.fellow_schemas import Viewport
from services.candle_service import CandleService
from services.stock_pools import (
    GECKO_TIMEFRAME,
    STOCK_POOLS,
    is_stock,
    ohlcv_request,
    parse_ohlcv,
    stock_pool,
)

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts" / "src"


def test_every_timeframe_the_app_serves_has_a_pool_bucket():
    assert set(GECKO_TIMEFRAME) == set(CandleService.timeframes())


def test_the_tokens_are_the_ones_the_vault_trades():
    source = (CONTRACTS / "Addresses.sol").read_text(encoding="utf-8")
    literals = dict(re.findall(r"address internal constant (\w+) = (0x[0-9a-fA-F]{40});", source))
    for symbol, pool in STOCK_POOLS.items():
        assert pool.token == literals[symbol], symbol


def test_the_request_prices_the_stock_in_dollars():
    url, params = ohlcv_request(stock_pool("NVDA"), "4h", 5000)
    assert url.endswith(f"/pools/{STOCK_POOLS['NVDA'].pool}/ohlcv/hour")
    assert params == {"aggregate": 4, "limit": 1000, "currency": "usd", "token": STOCK_POOLS["NVDA"].token}


def test_rows_become_binance_shaped_candles_oldest_first():
    body = {"data": {"attributes": {"ohlcv_list": [
        [3000, 3, 4, 2, 3.5, 30],
        [2000, 2, 3, 1, 2.5, 20],
        [2000, 2, 3, 1, 2.5, 20],
        [1000, "1", 2, 0.5, 1.5, 10],
        [500, None, 1, 1, 1, 1],
        "junk",
    ]}}}
    candles = parse_ohlcv(body)
    assert [c["time"] for c in candles] == [1_000_000, 2_000_000, 3_000_000]
    assert candles[0] == {"time": 1_000_000, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}
    assert parse_ohlcv({}) == []
    assert parse_ohlcv(None) == []


def test_candle_service_sends_a_stock_to_its_pool_and_a_pair_to_binance(monkeypatch):
    calls = []

    async def fake_stock(stock, timeframe, limit):
        calls.append(("pool", stock.symbol, timeframe))
        return []

    monkeypatch.setattr(CandleService, "_fetch_stock", staticmethod(fake_stock))
    asyncio.run(CandleService._fetch("NVDA", "1h", 10))
    assert calls == [("pool", "NVDA", "1h")]
    assert is_stock("tsla") and not is_stock("BTCUSDT")


def test_the_assistant_finds_a_stock_by_ticker_or_name_but_not_inside_a_word():
    assert cc.extract_symbol_from_message("is NVDA near support?") == "NVDA"
    assert cc.extract_symbol_from_message("what about tesla on the hourly") == "TSLA"
    assert cc.extract_symbol_from_message("apple double bottom?") == "AAPL"
    assert cc.extract_symbol_from_message("any spying going on") is None


def _ask(message, *, symbol="NVDA", window=True):
    request = cc.ChatRequest(
        message=message,
        symbol=symbol,
        timeframe="1h",
        window=Viewport(frm=1, to=2) if window else None,
    )
    return asyncio.run(cc.ask_question(request))


def test_an_alert_on_a_stock_is_declined_with_the_reason():
    reply = _ask("alert me when NVDA forms a double bottom")
    assert "can't watch it" in reply.response
    assert not (reply.data or {}).get("rule_draft")


def test_a_stock_question_without_a_window_asks_for_the_chart():
    reply = _ask("is NVDA near support?", window=False)
    assert "Open NVDA on the chart" in reply.response


def test_a_stock_question_goes_to_the_chart_reader_and_offers_no_alert(monkeypatch):
    seen = {}

    async def fake_scene(request, symbol):
        seen["symbol"] = symbol
        return {"symbol": symbol}

    class Answer:
        reply_md = "NVDA is sitting on support at 233.5."

        def model_dump(self, **_):
            return {"reply": self.reply_md}

    async def fake_answer(message, scene, history):
        return Answer()

    def no_subscriptions(*_a, **_k):
        raise AssertionError("a stock must not be offered an alert")

    monkeypatch.setattr(cc, "_scene_for", fake_scene)
    monkeypatch.setattr(cc.chart_fellow, "answer", fake_answer)
    monkeypatch.setattr(cc, "attach_subscriptions", no_subscriptions)
    # "buy" would send a crypto question to the strategy builder; a stock never goes there.
    reply = _ask("should I buy NVDA here?")
    assert seen["symbol"] == "NVDA"
    assert reply.response.startswith("NVDA is sitting on support")
