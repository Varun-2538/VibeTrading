"""
Which path answers a chat message.

The fellow must win pattern and level questions when a window is present.
It once did not: the legacy keyword branch for "double bottom" sat earlier in
the handler and answered first, so the new path was unreachable for exactly
the questions it was built for. Caught on production, pinned here.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controllers.chat_controller import detect_query_intent, named_symbol, route


@pytest.mark.parametrize("message", [
    "do you see a double bottom forming?",
    "is there support here?",
    "where is RSI right now",
    "what is the price",
    "anything interesting on this chart?",
])
def test_windowed_chart_questions_go_to_the_fellow(message):
    assert route(detect_query_intent(message), has_window=True) == "fellow"


def test_alert_requests_go_to_the_rule_parser_even_with_a_window():
    assert route(detect_query_intent("alert me when a doji forms"), has_window=True) == "alert"


@pytest.mark.parametrize("message", [
    "i want to build a stratergy where trade happends when ema 9 and 21 crossover happends ?",
    "buy ETH when EMA 9 crosses above EMA 21",
    "make a strategy that enters long when RSI crosses 30",
    "jab ema 9 aur 21 ka crossover ho tab trade karo",
])
def test_a_strategy_with_a_condition_is_drafted_as_a_rule(message):
    assert route(detect_query_intent(message), has_window=True) == "alert"


@pytest.mark.parametrize("message", [
    "is there a MACD cross?",
    "where is RSI right now",
    "what happens if I buy here?",
])
def test_questions_about_the_chart_are_not_drafted_as_rules(message):
    assert detect_query_intent(message) != "create_alert"


def test_a_coin_named_in_the_message_is_matched_on_whole_words():
    assert named_symbol("buy ETH when ema 9 crosses 21") == "ETHUSDT"
    assert named_symbol("ethusdt 1m") == "ETHUSDT"
    assert named_symbol("whether the dotted line holds") is None


def test_strategy_builds_keep_their_own_path():
    assert route(detect_query_intent("give me a trading strategy for BTC"), has_window=True) == "strategy"


def test_clients_without_a_window_get_the_legacy_branches():
    assert route(detect_query_intent("do you see a double bottom?"), has_window=False) == "legacy"
