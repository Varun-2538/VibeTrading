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
  "params": ONE of the two forms below
}

Form A - a sequence of events:
  {"agent": "sequence",
   "steps": [ one to four steps, in the order they must happen ],
   "within_bars": integer 1-50, how many bars a step may follow the previous one by (optional, default 3)}

Form B - a chart pattern:
  {"agent": "pattern",
   "kinds": list from W (double bottom), M (double top), HS (head and shoulders), IHS (inverse head and shoulders), CUP (cup and handle),
   "states": ["confirmed"] by default; add "forming" or "approaching" only if the user asks to be told while it is still developing,
   "min_confidence": number 0-100 (optional, default 70)}

A step is exactly one of:
  {"type": "candle", "shape": one of SHAPES below, "max_body_pct": number 0-50 (optional, doji only, default 10)}
  {"type": "indicator", "indicator": "rsi", "period": integer 2-200, "cross": "above" | "below", "level": number 0-100}
  {"type": "structure", "event": "sweep" | "breakout" | "rejection" | "pullback", "side": "bullish" | "bearish"}
  {"type": "ema_cross", "fast": integer 1-400, "slow": integer 2-400, "cross": "above" | "below"}
  {"type": "macd_cross", "fast": 12, "slow": 26, "signal": 9, "against": "signal" | "zero", "cross": "above" | "below"}
  {"type": "stoch_cross", "k": 14, "k_smooth": 3, "d": 3, "against": "d" | "level", "level": number 0-100, "cross": "above" | "below"}
  {"type": "bollinger", "band": "upper" | "middle" | "lower", "cross": "above" | "below", "period": 20, "std": 2}
  {"type": "bollinger_squeeze", "period": 20, "std": 2, "lookback": integer 10-1000}
  {"type": "vwap_cross", "anchor": "day" | "week", "cross": "above" | "below"}
  {"type": "volume_spike", "multiple": number above 1, "period": 20}
  {"type": "atr_expansion", "multiple": number above 1, "period": 14}

SHAPES: __SHAPES__
Structure wording: "liquidity sweep", "stop hunt", "sweep the lows", "liquidity grab below" -> sweep bullish; "sweep the highs" -> sweep bearish; "breakout above resistance" -> breakout bullish; "breakdown", "break below support" -> breakout bearish; "rejection at support", "bounce off support" -> rejection bullish; "rejection at resistance" -> rejection bearish; "pullback in an uptrend", "dip in the trend" -> pullback bullish; "pullback in a downtrend", "relief rally" -> pullback bearish. "Smart money" or "institutional" sweep means the sweep event.
Indicator wording: "golden cross" -> ema_cross fast 50 slow 200 above; "death cross" -> ema_cross fast 50 slow 200 below; "price crosses the 200 EMA" -> ema_cross fast 1 slow 200 (fast 1 is the close itself); "MACD crossover"/"MACD bullish cross" -> macd_cross against signal above; "MACD crosses zero" -> against zero; "stochastic oversold cross" -> stoch_cross against level, level 20, above; "overbought" -> level 80, below; "stoch %K crosses %D" -> against d; "closes above the upper band"/"Bollinger breakout" -> bollinger upper above; "loses the lower band" -> bollinger lower below; "squeeze", "bands tightening", "coiling", "low volatility" -> bollinger_squeeze; "crosses VWAP", "reclaims VWAP" -> vwap_cross above, anchor day (use week when the sentence says weekly, and always on the 1d timeframe); "volume spike", "unusual volume", "volume climax" -> volume_spike; "range expansion", "wide bar", "volatility expansion", "big candle" -> atr_expansion.
Synonyms: "pin bar" or "bullish pin" or "dragonfly" -> hammer; "inverted hammer" or "bearish pin" or "gravestone" -> shooting_star; "engulfing" alone -> ask which by direction words, default bullish_engulfing; "inside candle" or "harami" -> inside_bar.

Rules:
- Use Form B when the sentence names a chart pattern (double bottom/top, W, M, head and shoulders, inverse head and shoulders, cup and handle). Use Form A for candles, indicators and structure events. A pattern cannot be a step inside a sequence.
- Only the shapes, indicators, structure events and pattern kinds listed exist. If the sentence needs anything else (open interest, funding rate, long/short ratio, order flow, Ichimoku, three white soldiers, morning star), output {"error": "<one sentence saying which part is unsupported>"}.
- "RSI crossover of 14" or "RSI 14 crossover" means period 14; if the level is not stated, use 30 for "above"/bullish/oversold wording and 70 for "below"/bearish/overbought wording; if direction is not stated, use "above" with level 30.
- Add "lookback": integer 50-1000 to Form A when a step is slow to warm up: at least the slow EMA, or the Bollinger period plus its squeeze lookback, plus room for the steps. A squeeze over 120 bars needs 400.
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
        params.setdefault("agent", "pattern" if "kinds" in params else "sequence")
        data["params"] = params

    if not data.get("name") and isinstance(params, dict) and params.get("kinds"):
        data["name"] = f"{data['symbol']} {'/'.join(params['kinds'])} {'/'.join(params.get('states', ['confirmed']))}"[:80]
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


KIND_NAMES = {
    "W": "double bottom", "M": "double top", "HS": "head and shoulders",
    "IHS": "inverse head and shoulders", "CUP": "cup and handle",
}


def describe_draft(draft: RuleCreate) -> str:
    """One line for the confirm card, whichever form the draft took."""
    params = draft.params.model_dump()
    if params.get("agent") == "pattern":
        kinds = " or ".join(KIND_NAMES.get(k, k) for k in params.get("kinds", []))
        states = "/".join(params.get("states", ["confirmed"]))
        return f"{kinds} {states}, confidence at least {params.get('min_confidence', 70):g}%"
    within = params.get("within_bars", 3)
    return (
        f"{describe_steps(params.get('steps', []))}, "
        f"each step within {within} bar{'s' if within != 1 else ''} of the last"
    )


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
