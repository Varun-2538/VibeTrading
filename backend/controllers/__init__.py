from .strategy_controller import router as strategy_router
from .ohlc_controller import router as ohlc_router
from .websocket_controller import router as websocket_router
from .rules_controller import router as rules_router
from .auth_controller import router as auth_router
from .history_controller import router as history_router
from .backtest_controller import router as backtest_router
from .execution_controller import router as execution_router

__all__ = [
    "strategy_router",
    "ohlc_router",
    "websocket_router",
    "rules_router",
    "auth_router",
    "history_router",
    "backtest_router",
    "execution_router",
]
