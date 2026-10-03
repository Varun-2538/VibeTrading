"""
Turns a sentence into a rule draft.

The model's only job is to say what the user meant, as JSON. Whether that JSON
is a rule is decided by the same Pydantic model the API validates against, so
a hallucinated indicator, an impossible level or a missing step is refused here
exactly as it would be at POST /api/rules - and the reply says so, instead of a
wrong rule being drafted. The engine never calls this; parsing is the whole of
the LLM's involvement.
"""
import json
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from openai import RateLimitError
from pydantic import ValidationError

from agents.llm import make_llm
from analysis.candles import SHAPES
from analysis.sequence import describe_steps
from models.rule_schemas import RuleCreate


class RuleParseError(Exception):
    """The sentence could not be read as a rule. Message is safe to show."""


class LLMBusy(Exception):
    """The provider rate-limited us; try again shortly."""


SYSTEM_PROMPT_TEMPLATE = """You convert a trader's sentence into ONE alert rule as JSON. Output JSON only, no prose, no code fences.

Schema (every key required unless marked optional):
{
  "name": string, at most 80 chars, short human label,
  "symbol": one of BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT ADAUSDT DOGEUSDT DOTUSDT AVAXUSDT,
  "timeframe": one of 1m 5m 15m 30m 1h 4h 1d,
  "params": {
    "agent": "sequence",
    "steps": [ one to four steps, in the order they must happen ],
    "within_bars": integer 1-50, how many bars a step may follow the previous one by (optional, default 3)
  }
}

A step is exactly one of:
  {"type": "candle", "shape": one of SHAPES below, "max_body_pct": number 0-50 (optional, doji only, default 10)}
  {"type": "indicator", "indicator": "rsi", "period": integer 2-200, "cross": "above" | "below", "level": number 0-100}

SHAPES: __SHAPES__
Synonyms: "pin bar" or "bullish pin" or "dragonfly" -> hammer; "inverted hammer" or "bearish pin" or "gravestone" -> shooting_star; "engulfing" alone -> ask which by direction words, default bullish_engulfing; "inside candle" or "harami" -> inside_bar.

Rules:
- Only the shapes and indicators listed exist. If the sentence needs anything else (MACD, EMA, volume, price levels, three white soldiers, morning star), output {"error": "<one sentence saying which part is unsupported>"}.
- "RSI crossover of 14" or "RSI 14 crossover" means period 14; if the level is not stated, use 30 for "above"/bullish/oversold wording and 70 for "below"/bearish/overbought wording; if direction is not stated, use "above" with level 30.
- "followed by", "then", "after" set step order. "within N candles/bars" sets within_bars.
- If the sentence names no symbol, use the default symbol given. Same for timeframe.
- If the sentence is not asking for an alert on a condition, output {"error": "..."}.
"""

SYSTEM_PROMPT = SYSTEM_PROMPT_TEMPLATE.replace("__SHAPES__", ", ".join(SHAPES))


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def parse_draft(raw: str, default_symbol: Optional[str], default_timeframe: str) -> RuleCreate:
    """
    Validate model output into a RuleCreate, or raise RuleParseError.

    Pure, so tests can feed it canned JSON without a model in the loop.
    """
    try:
        data: Dict[str, Any] = json.loads(_strip_fences(raw))
    except (json.JSONDecodeError, TypeError):
        raise RuleParseError("I couldn't read that as a rule. Try: \"alert me when a doji forms and RSI(14) crosses above 30 on BTC 1h\".")

    if not isinstance(data, dict):
        raise RuleParseError("I couldn't read that as a rule.")

    if "error" in data:
        raise RuleParseError(str(data["error"]))

    data.setdefault("symbol", default_symbol)
    data.setdefault("timeframe", default_timeframe)
    if not data.get("symbol"):
        raise RuleParseError("Which pair? Name one, e.g. BTC, ETH or SOL.")

    params = data.get("params") or {}
    if isinstance(params, dict):
        params.setdefault("agent", "sequence")
        data["params"] = params

    if not data.get("name") and isinstance(params, dict) and params.get("steps"):
        try:
            data["name"] = f"{data['symbol']} {describe_steps(params['steps'])}"[:80]
        except (KeyError, TypeError):
            pass

    try:
        return RuleCreate(**data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ()))
        raise RuleParseError(f"That rule isn't valid ({where}: {first.get('msg')}).")


async def draft_rule(message: str, default_symbol: Optional[str], default_timeframe: str) -> RuleCreate:
    """One short, deterministic call. Nothing is armed here."""
    llm = make_llm(temperature=0, max_tokens=500)

    user = (
        f"Default symbol: {default_symbol or 'none'}\n"
        f"Default timeframe: {default_timeframe}\n"
        f"Sentence: {message}"
    )

    try:
        response = await llm.ainvoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user)]
        )
    except RateLimitError:
        raise LLMBusy("The assistant is busy right now - try again in a minute.")

    content = response.content if isinstance(response.content, str) else str(response.content)
    return parse_draft(content, default_symbol, default_timeframe)
