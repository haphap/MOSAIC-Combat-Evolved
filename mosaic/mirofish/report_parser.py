"""Parse a MiroFish prediction report (free-form Chinese markdown) into a
structured :class:`ReportSignal` (direction / confidence / regime / drift / tail
risks / summary).

Replaces the earlier crude bull-minus-bear keyword net, which mapped a clearly
bullish report (explicit ``RISK_ON`` + ``+1.2%~+2.8%``) to NEUTRAL/0 because the
report also mentions risks. This rule-based parser honours explicit regime tokens
and directional percentage forecasts the report emits, falling back to weighted
keyword scoring.

Stdlib only (``re``) so the adapter stays deps-light. The mapping is still lossy —
MiroFish predicts narratives, not OHLCV — so treat the output as a directional
view, not a price forecast (callers mark scenarios ``mapping_lossy=True``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Weighted cues; weight ≈ how decisive the phrase is.
_BULL = (
    (r"risk[\s_\-]?on", 2.5), ("看多", 1.5), ("做多", 1.3), ("利好", 1.0), ("上涨", 1.0),
    ("上行", 1.0), ("反弹", 1.0), ("回暖", 1.2), ("走强", 1.0), ("乐观", 0.8),
    ("bullish", 1.5), ("rally", 1.0),
)
_BEAR = (
    (r"risk[\s_\-]?off", 2.5), ("看空", 1.5), ("做空", 1.3), ("避险", 1.8), ("利空", 1.0),
    ("下跌", 1.0), ("下行", 1.0), ("回调", 1.0), ("走弱", 1.0), ("悲观", 0.8),
    ("崩", 1.5), ("bearish", 1.5), ("crash", 1.0),
)
_NEUTRAL = ((r"\bneutral\b", 2.0), ("中性", 1.5), ("震荡", 1.0), ("区间", 0.8), ("观望", 0.8))

_ON = ((r"risk[\s_\-]?on", 1.0), (r"风险偏好[^。\n]{0,8}(?:上行|回升|抬升|转向)", 1.0), ("偏多", 1.0))
_OFF = ((r"risk[\s_\-]?off", 1.0), ("避险", 1.0), (r"风险偏好[^。\n]{0,8}(?:下行|回落)", 1.0), ("偏空", 1.0))

# A range may carry a single trailing % ("+1.2~+2.8%") or one per number
# ("+1.2%~+2.8%"); both must yield the midpoint, so the first % is optional.
_UP_PCT = re.compile(
    r"(?:上行|上涨|上升|回暖|反弹|走强)[^%\n]{0,16}?\+?\s*(\d+(?:\.\d+)?)\s*(?:%\s*)?"
    r"(?:[~\-—至]\s*\+?\s*(\d+(?:\.\d+)?)\s*)?%"
)
_DOWN_PCT = re.compile(
    r"(?:下行|下跌|下挫|回调|走弱)[^%\n]{0,16}?-?\s*(\d+(?:\.\d+)?)\s*(?:%\s*)?"
    r"(?:[~\-—至]\s*-?\s*(\d+(?:\.\d+)?)\s*)?%"
)

# Clauses describing tail/stress scenarios — excluded from the base/overall view
# so a downside stress range can't invert the base scenario's drift/direction.
_TAIL_CUE = re.compile(r"尾部|风险情形|压力情形|极端|stress|最坏|下行风险|悲观情形", re.IGNORECASE)
_CLAUSE_SPLIT = re.compile(r"[。\n；;，,、]")

_DRIFT_CLAMP = 0.30
_MAX_TAIL = 5


@dataclass
class ReportSignal:
    direction: str          # "bullish" | "bearish" | "neutral"
    confidence: float       # 0..1
    regime: str             # "RISK_ON" | "RISK_OFF" | "NEUTRAL"
    drift: float            # estimated horizon return, e.g. +0.02 (clamped ±0.30)
    tail_risks: list = field(default_factory=list)
    summary: str = ""

    @property
    def signed_score(self) -> float:
        """Back-compat scalar (was ``report_sentiment``): +conf bullish, -conf bearish."""
        sign = {"bullish": 1.0, "bearish": -1.0}.get(self.direction, 0.0)
        return round(sign * self.confidence, 4)


def _weighted(text: str, cues) -> float:
    return sum(w * len(re.findall(pat, text, re.IGNORECASE)) for pat, w in cues)


def _directional_pcts(md: str) -> list[float]:
    """Signed return figures attached to up/down language → list of fractions."""
    out: list[float] = []
    for rx, sign in ((_UP_PCT, 1.0), (_DOWN_PCT, -1.0)):
        for m in rx.finditer(md):
            nums = [float(x) for x in m.groups() if x]
            if nums:
                out.append(sign * sum(nums) / len(nums) / 100.0)
    return out


def _non_tail_text(md: str) -> str:
    """Drop tail/stress clauses → the base/overall forecast text. Falls back to the
    whole report if every clause looks like a stress section."""
    kept = [c for c in _CLAUSE_SPLIT.split(md) if c.strip() and not _TAIL_CUE.search(c)]
    return "。".join(kept) if kept else md


def _tail_risks(md: str) -> list[str]:
    risks: list[str] = []
    for m in re.finditer(r"尾部风险[：:，,]?\s*([^。\n]{2,60})", md):
        frag = m.group(1).strip(" 。.;；")
        for part in re.split(r"[、,，;；/]| 和 ", frag):
            part = part.strip()
            if part and part not in risks:
                risks.append(part)
    return risks[:_MAX_TAIL]


def _summary(md: str) -> str:
    for line in md.splitlines():  # prefer a blockquote
        s = line.strip()
        if s.startswith(">"):
            return s.lstrip("> ").strip()[:200]
    for line in md.splitlines():  # else first non-heading line
        s = line.strip()
        if s and not s.startswith("#"):
            return s[:200]
    return ""


def parse_report(md: str) -> ReportSignal:
    md = md or ""
    # Base/overall view excludes tail-risk clauses (so a stress downside range
    # can't invert the base scenario); tail risks are extracted from the full doc.
    base = _non_tail_text(md)
    bull, bear, neu = _weighted(base, _BULL), _weighted(base, _BEAR), _weighted(base, _NEUTRAL)

    pcts = _directional_pcts(base)
    pct_drift = sum(pcts) / len(pcts) if pcts else None

    score = bull - bear
    if pct_drift is not None:
        score += (1.0 if pct_drift > 0 else -1.0) * 2.0

    if score > 0.75:
        direction = "bullish"
    elif score < -0.75:
        direction = "bearish"
    else:
        direction = "neutral"

    on, off = _weighted(base, _ON), _weighted(base, _OFF)
    if on > off and on > 0:
        regime = "RISK_ON"
    elif off > on and off > 0:
        regime = "RISK_OFF"
    elif neu > max(bull, bear):
        regime = "NEUTRAL"
    else:
        regime = {"bullish": "RISK_ON", "bearish": "RISK_OFF"}.get(direction, "NEUTRAL")

    if pct_drift is not None:
        drift = pct_drift
    else:
        drift = {"bullish": 0.03, "bearish": -0.03}.get(direction, 0.0)
    drift = max(-_DRIFT_CLAMP, min(_DRIFT_CLAMP, drift))

    strength = abs(score) + (1.0 if pct_drift is not None else 0.0)
    total = bull + bear + neu
    agree = (abs(bull - bear) / total) if total else 0.0
    confidence = max(0.0, min(1.0, 0.35 + 0.12 * strength + 0.25 * agree))
    if direction == "neutral":
        confidence = min(confidence, 0.5)

    return ReportSignal(
        direction=direction,
        confidence=round(confidence, 3),
        regime=regime,
        drift=round(drift, 4),
        tail_risks=_tail_risks(md),
        summary=_summary(md),
    )
