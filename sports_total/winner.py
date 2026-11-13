"""วิเคราะห์ผู้ชนะ (moneyline) ใช้ร่วมกันทุกกีฬา

- รับโอกาสชนะจากโมเดลของแต่ละกีฬา (สองทาง: home/away หรือสามทาง: home/draw/away)
- ถ้ามีราคาผู้ชนะ (moneyline) จากเจ้ามือหรือที่ผู้ใช้กรอก: ตัดค่าน้ำแล้วผสม โมเดล 40% / ตลาด 60%
  แบบเดียวกับสกอร์รวม เพื่อลดความมั่นใจเกินจริงของโมเดลที่ใช้แค่ผลย้อนหลัง
- ความได้เปรียบ (edge) = โอกาสหลังผสม − โอกาสที่ราคาบอก
"""

from __future__ import annotations

from dataclasses import dataclass

from . import stats

LEAN_EDGE = 0.03
STRONG_EDGE = 0.06
BIG_GAP = 0.15       # โมเดลกับตลาดต่างกันเกิน 15 จุด -> ไม่ให้ระดับ "แนะนำ"


@dataclass
class Moneyline:
    provider: str
    home: float | None          # ราคาแบบอเมริกัน
    away: float | None
    draw: float | None = None

    def odds(self) -> dict[str, float] | None:
        out = {"home": self.home, "away": self.away}
        if self.draw is not None:
            out["draw"] = self.draw
        return out if all(v is not None for v in out.values()) else None


@dataclass
class WinnerEval:
    model: dict[str, float]
    market: dict[str, float] | None     # โอกาสจากราคา (ตัดค่าน้ำแล้ว)
    odds: dict[str, float] | None
    prob: dict[str, float]              # โอกาสที่ใช้ตัดสิน (หลังผสม)
    edges: dict[str, float] | None
    pick: str | None
    strength: str
    source: str

    @property
    def favorite(self) -> str:
        return max(self.prob, key=self.prob.get)

    def to_doc(self) -> dict:
        r = lambda d: None if d is None else {k: round(v, 4) for k, v in d.items()}
        return {"model": r(self.model), "market": r(self.market), "odds": self.odds,
                "prob": r(self.prob), "edges": r(self.edges), "pick": self.pick,
                "strength": self.strength, "source": self.source}


def no_vig(odds: dict[str, float]) -> dict[str, float]:
    imp = {k: 1 / stats.american_to_decimal(v) for k, v in odds.items()}
    s = sum(imp.values())
    return {k: v / s for k, v in imp.items()}


def evaluate_winner(model: dict[str, float], ml: Moneyline | None, weight: float = 0.4,
                    quality: str = "สูง") -> WinnerEval:
    s = sum(model.values())
    model = {k: v / s for k, v in model.items()} if s > 0 else model
    odds = ml.odds() if ml else None
    if odds is not None and set(odds) != set(model):
        odds = None   # ราคาไม่ตรงชนิด (เช่น ตลาดสองทางกับโมเดลสามทาง)
    if odds is None:
        return WinnerEval(model, None, None, dict(model), None, None, "ไม่มีราคา", "โมเดลล้วน")

    market = no_vig(odds)
    prob = {k: weight * model[k] + (1 - weight) * market[k] for k in model}
    edges = {k: prob[k] - 1 / stats.american_to_decimal(odds[k]) for k in model}
    best = max(edges, key=edges.get)
    pick, strength = None, "ผ่าน"
    if edges[best] >= STRONG_EDGE:
        pick, strength = best, "แนะนำ"
    elif edges[best] >= LEAN_EDGE:
        pick, strength = best, "เอนเอียง"
    gap = max(abs(model[k] - market[k]) for k in model)
    if strength == "แนะนำ" and (quality == "ต่ำ" or gap >= BIG_GAP):
        strength = "เอนเอียง"
    return WinnerEval(model, market, odds, prob, edges, pick, strength, ml.provider)
