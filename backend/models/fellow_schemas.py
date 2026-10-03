"""
What the chart fellow is allowed to say back.

Validated with the same discipline as rule drafts: the model proposes JSON,
this schema decides whether it is an answer. A mark the schema cannot type is
not drawn; a finding without a kind from the vocabulary is not shown.
"""
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class HLine(BaseModel):
    """A horizontal line at a price - a level, a neckline, a target."""

    type: Literal["hline"] = "hline"
    price: float
    label: str = Field(default="", max_length=40)


class BarMark(BaseModel):
    """A marker on one candle - a doji, a cross, a rejection."""

    type: Literal["bar"] = "bar"
    time: int = Field(description="Bar open time, unix ms, exactly as in the scene")
    position: Literal["above", "below"] = "below"
    shape: Literal["circle", "arrowUp", "arrowDown", "square"] = "circle"
    text: str = Field(default="", max_length=24)


class PolylinePoint(BaseModel):
    time: int
    price: float


class Polyline(BaseModel):
    """Pattern geometry - the legs of a W or M through its pivot points."""

    type: Literal["polyline"] = "polyline"
    points: List[PolylinePoint] = Field(min_length=2, max_length=8)
    label: str = Field(default="", max_length=40)


class Box(BaseModel):
    """A zone between two prices over a span of bars."""

    type: Literal["box"] = "box"
    from_time: int = Field(alias="from")
    to_time: int = Field(alias="to")
    price_top: float
    price_bottom: float
    label: str = Field(default="", max_length=40)

    model_config = {"populate_by_name": True}


Mark = Annotated[Union[HLine, BarMark, Polyline, Box], Field(discriminator="type")]


class Finding(BaseModel):
    """
    One thing the user asked about, answered present or not.

    `grounded` is set by the guard, never by the model: False means the model
    asked to mark something the detectors did not find, and those marks were
    dropped.
    """

    kind: Literal["level", "pattern", "candle", "indicator", "structure"]
    label: str = Field(min_length=1, max_length=60)
    present: bool
    confidence: float = Field(default=0, ge=0, le=100)
    why: str = Field(default="", max_length=300)
    marks: List[Mark] = Field(default_factory=list, max_length=12)
    grounded: bool = True


class FellowAnswer(BaseModel):
    reply_md: str = Field(min_length=1, max_length=2000)
    findings: List[Finding] = Field(default_factory=list, max_length=12)
    # Things asked about that no detector can see, by name.
    not_visible: List[str] = Field(default_factory=list, max_length=12)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=300)


class PatternSettings(BaseModel):
    strictness: str = "balanced"
    source: str = "wick"
    scale: str = "swing"


class Viewport(BaseModel):
    frm: Optional[int] = Field(default=None, alias="from")
    to: Optional[int] = None

    model_config = {"populate_by_name": True}
