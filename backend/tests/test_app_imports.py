"""
Every controller must import.

A syntax error in a controller is invisible to the rest of the suite, which
imports only the modules it tests. One shipped: a bad escape in
chat_controller crash-looped the production container while 176 tests passed.
This is the cheapest possible guard against that class of failure.
"""
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CONTROLLERS = [
    "controllers.analysis_controller",
    "controllers.auth_controller",
    "controllers.chat_controller",
    "controllers.ohlc_controller",
    "controllers.rules_controller",
    "controllers.strategy_controller",
    "controllers.websocket_controller",
]


@pytest.mark.parametrize("module", CONTROLLERS)
def test_controller_imports(module):
    assert importlib.import_module(module).router is not None
