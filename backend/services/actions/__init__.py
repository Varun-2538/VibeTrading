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

# Phase 1 ships alerts only. Deliberately not a plugin loader - one dict is
# easier to audit, and auditability matters once an entry can spend money.
ACTIONS: Dict[str, Action] = {
    "alert": AlertAction(),
}

__all__ = ["ACTIONS", "Action", "ActionResult", "AlertAction"]
