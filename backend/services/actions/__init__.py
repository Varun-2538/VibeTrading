"""
What happens when a rule fires.

The registry is the seam for Phase 2: a DEX executor registers as "dex_trade"
and the rule's `action` JSONB carries its configuration, so adding execution
needs no schema change and no change to the engine.

Actions consume a Signal, never raw detector output, so retuning the pattern
detector cannot change what an executor receives.
"""
from typing import Dict

from services.actions.base import Action, ActionResult
from services.actions.alert import AlertAction
from services.actions.dex_trade import DexTradeAction

# Deliberately not a plugin loader - one dict is easier to audit, and auditability
# matters now that an entry here can spend money.
#
# dex_trade queues; it does not trade. Nothing it queues is claimed unless the
# global switch is on and the owner's account is out of 'off', both of which ship
# false, and unless the rule has an armed policy backed by a passing backtest.
ACTIONS: Dict[str, Action] = {
    "alert": AlertAction(),
    "dex_trade": DexTradeAction(),
}

__all__ = ["ACTIONS", "Action", "ActionResult", "AlertAction", "DexTradeAction"]
