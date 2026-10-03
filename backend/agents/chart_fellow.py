"""
The chart fellow: a trader looking at the same screen, answering from the scene.

Two rules make this safe to put in front of a chart:

1. The model only ever sees the scene - detector output for the candles on
   screen - never pixels and never raw history. It cannot know a level the
   detectors did not find.
2. Nothing it asks to mark is drawn unless the guard can find it in the scene.
   A model that invents a support line gets its line dropped and the finding
   flagged; the reply says so. The chart draws detector facts only.

The model's contribution is the narration and the judgement of what the
question was about. That is the part it is good at.
"""
import json
from typing import Any, Dict, List, Sequence, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from openai import RateLimitError
from pydantic import ValidationError

from agents.llm import make_llm
from models.fellow_schemas import (
    BarMark,
    Box,
    ChatTurn,
    FellowAnswer,
    HLine,
    Polyline,
)

# A marked price must sit this close to a scene price to count as the same.
PRICE_TOLERANCE = 0.0005  # 0.05%

MAX_HISTORY_TURNS = 8  # four exchanges


class FellowError(Exception):
    """The reply could not be read as an answer. Message is safe to show."""


class LLMBusy(Exception):
    """Rate-limited by the provider."""


SYSTEM_PROMPT = """You are a fellow trader sitting next to the user, looking at the same chart. You talk plainly, like a colleague - no hedging boilerplate, no lectures, no emoji.

You are given a SCENE: what the detectors found in exactly the candles on the user's screen. It is the only thing you can see. You never see pixels and you do not know anything about the chart that is not in the scene.

Hard rules:
- Only assert what the scene contains. If the scene has no double bottom, you do not see one. If it lists a support level at a price, you may say so and mark it at that exact price.
- The scene's "vocabulary" lists what you can see. If the user asks about something outside it, or anything in "unsupported" (open interest, short covering, long unwinding, order flow...), say you cannot see that yet and put its name in not_visible. Do not guess. not_visible holds only things the user actually asked about - never list the unsupported set unprompted.
- Talk like a trader, not like someone reading JSON: never mention field names, "null", "the scene" or "the data provided". Say "no pullback right now", not "pullback is null".
- Every mark must copy a price or bar time from the scene verbatim: hline prices from levels/neckline/target/structure event levels, bar times from candles.shapes/last/indicator crosses/structure events, polyline points from a pattern's points or the structure swings. Marks that do not match the scene will be removed.
- "Smart money", "institutional", "stop hunt", "liquidity grab" all mean the structure events: a sweep is a wick through a level with a close back on the original side. Describe what the bar did; never claim to know who traded. Structure gives the trend from swings (HH/HL or LH/LL), recent breakouts/sweeps/rejections at levels, and whether the newest bar is a pullback.
- Answer what was asked. For each thing the user asked about, add one finding with present true or false. Absent things are useful answers: "no, I don't see a W here" is a good reply.
- Keep reply_md short - a few sentences a trader would actually say. Never write raw millisecond timestamps in reply_md; say "the latest candle", "three bars back" or similar. Timestamps belong in marks only.

Output JSON only, no prose outside it, no code fences:
{
  "reply_md": string,
  "findings": [
    {"kind": "level"|"pattern"|"candle"|"indicator"|"structure",
     "label": string, "present": boolean, "confidence": 0-100, "why": string,
     "marks": [
       {"type":"hline","price":number,"label":string} |
       {"type":"bar","time":int_ms,"position":"above"|"below","shape":"circle"|"arrowUp"|"arrowDown"|"square","text":string} |
       {"type":"polyline","points":[{"time":int_ms,"price":number},...],"label":string} |
       {"type":"box","from":int_ms,"to":int_ms,"price_top":number,"price_bottom":number,"label":string}
     ]}
  ],
  "not_visible": [string]
}
"""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


# --- the guard ---------------------------------------------------------------


def _scene_prices(scene: Dict[str, Any]) -> List[float]:
    prices: List[float] = []
    for side in ("support", "resistance"):
        prices += [float(l["price"]) for l in scene.get("levels", {}).get(side, [])]
    for p in scene.get("patterns", []):
        prices += [float(p["neckline"]), float(p["target"])]
        prices += [float(pt["price"]) for pt in p.get("points", {}).values()]
    ema = scene.get("indicators", {}).get("ema", {})
    prices += [float(v) for k, v in ema.items() if k in ("20", "50")]
    st = scene.get("structure") or {}
    prices += [float(p["price"]) for p in st.get("swings", [])]
    prices += [float(e["level"]) for e in st.get("events", [])]
    if st.get("pullback"):
        prices.append(float(st["pullback"]["holds"]["price"]))
    return prices


def _scene_times(scene: Dict[str, Any]) -> set:
    times = set()
    for c in scene.get("candles", {}).get("last", []):
        times.add(int(c["t"]))
    for s in scene.get("candles", {}).get("shapes", []):
        times.add(int(s["t"]))
    for p in scene.get("patterns", []):
        for pt in p.get("points", {}).values():
            times.add(int(pt["t"]))
    ind = scene.get("indicators", {})
    for c in ind.get("rsi", {}).get("recent_crosses", []):
        times.add(int(c["t"]))
    for name in ("ema", "macd"):
        cross = ind.get(name, {}).get("recent_cross")
        if cross:
            times.add(int(cross["t"]))
    st = scene.get("structure") or {}
    times.update(int(p["t"]) for p in st.get("swings", []))
    times.update(int(e["t"]) for e in st.get("events", []))
    if st.get("pullback"):
        times.add(int(st["pullback"]["holds"]["t"]))
    return times


def _pattern_points(scene: Dict[str, Any]) -> set:
    """Points a polyline may pass through: pattern pivots and swing points."""
    pts = set()
    for p in scene.get("patterns", []):
        for pt in p.get("points", {}).values():
            pts.add((int(pt["t"]), float(pt["price"])))
    for sp in (scene.get("structure") or {}).get("swings", []):
        pts.add((int(sp["t"]), float(sp["price"])))
    return pts


def _near(price: float, candidates: Sequence[float]) -> bool:
    return any(abs(price - c) <= abs(c) * PRICE_TOLERANCE for c in candidates)


def _in_window(t: int, scene: Dict[str, Any]) -> bool:
    w = scene.get("window") or {}
    lo, hi = w.get("from"), w.get("to")
    return lo is not None and hi is not None and lo <= t <= hi


def ground(answer: FellowAnswer, scene: Dict[str, Any]) -> Tuple[FellowAnswer, int]:
    """
    Drop every mark the scene cannot vouch for. Returns the answer and how
    many marks were removed.

    Deterministic and after validation, so a well-typed but invented mark is
    still refused. A finding that loses marks is flagged grounded=False rather
    than deleted: the model's claim is still shown, just not drawn.
    """
    prices = _scene_prices(scene)
    times = _scene_times(scene)
    points = _pattern_points(scene)
    dropped = 0

    for finding in answer.findings:
        kept = []
        for mark in finding.marks:
            ok = False
            if isinstance(mark, HLine):
                ok = _near(mark.price, prices)
            elif isinstance(mark, BarMark):
                ok = mark.time in times
            elif isinstance(mark, Polyline):
                ok = all(
                    any(t == pt.time and _near(pt.price, [price]) for t, price in points)
                    for pt in mark.points
                )
            elif isinstance(mark, Box):
                ok = (
                    _in_window(mark.from_time, scene)
                    and _in_window(mark.to_time, scene)
                    and _near(mark.price_top, prices)
                    and _near(mark.price_bottom, prices)
                )
            if ok:
                kept.append(mark)
            else:
                dropped += 1
        if len(kept) < len(finding.marks):
            finding.grounded = False
        finding.marks = kept

    return answer, dropped


# --- parsing -----------------------------------------------------------------


def parse_answer(raw: str, scene: Dict[str, Any]) -> FellowAnswer:
    """Validate model output and ground it. Pure; tests feed canned JSON."""
    try:
        data = json.loads(_strip_fences(raw))
    except (json.JSONDecodeError, TypeError):
        raise FellowError("I lost the thread there - ask me again?")
    if not isinstance(data, dict):
        raise FellowError("I lost the thread there - ask me again?")

    try:
        answer = FellowAnswer(**data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise FellowError(f"I couldn't put that answer together ({first.get('msg')}).")

    answer, dropped = ground(answer, scene)
    if dropped:
        answer.reply_md += (
            f"\n\n_({dropped} mark{'s' if dropped != 1 else ''} left off: "
            f"I described something the detectors did not actually find on this window.)_"
        )
    return answer


async def answer(
    question: str,
    scene: Dict[str, Any],
    history: Sequence[ChatTurn] = (),
) -> FellowAnswer:
    """One call. The scene rides in the same human turn as the question."""
    # max_tokens covers the model's private reasoning as well as the answer. A
    # reasoning model given 700 spent them all thinking about a compound
    # question and returned nothing; the real answer is 400-600 tokens, so
    # this leaves room for thinking without inviting an essay. Low effort keeps
    # that thinking short, and json_object makes the content parseable even
    # when the model would rather chat.
    llm = make_llm(
        temperature=0.2,
        max_tokens=1600,
        reasoning_effort="low",
        response_format={"type": "json_object"},
    )

    messages: List[Any] = [SystemMessage(content=SYSTEM_PROMPT)]
    for turn in list(history)[-MAX_HISTORY_TURNS:]:
        cls = HumanMessage if turn.role == "user" else AIMessage
        messages.append(cls(content=turn.content))
    messages.append(
        HumanMessage(
            content=f"SCENE:\n{json.dumps(scene, separators=(',', ':'))}\n\nQUESTION: {question}"
        )
    )

    try:
        response = await llm.ainvoke(messages)
    except RateLimitError:
        raise LLMBusy("I'm rate-limited for a minute - ask again shortly.")

    content = response.content if isinstance(response.content, str) else str(response.content)
    if not content.strip():
        # Truncated inside its own reasoning, or refused. Either way there is
        # nothing to parse, and the generic parse error would mislead.
        raise FellowError("That one got away from me - ask it in a shorter form?")
    return parse_answer(content, scene)
