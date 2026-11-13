"""แกนหลักของการวิเคราะห์สกอร์รวม

ขั้นตอน
1. ดึงผลการแข่งขันล่าสุด N นัดของทั้งสองทีม (เฉพาะเกมที่จบก่อนนัดที่วิเคราะห์)
2. คำนวณค่าเฉลี่ยคะแนนได้/เสีย แบบถ่วงน้ำหนักให้เกมล่าสุดสำคัญกว่า
3. หดค่าเข้าหาค่าเฉลี่ยลีก (shrinkage) เมื่อข้อมูลน้อย
4. คาดการณ์คะแนนแต่ละทีม = ค่าเฉลี่ยลีก x พลังบุก(ทีมเรา) x พลังรับ(คู่แข่ง) +/- ความได้เปรียบเจ้าบ้าน
5. แปลงเป็นความน่าจะเป็น สูง/ต่ำ ด้วยการแจกแจงที่เหมาะกับแต่ละกีฬา
6. เทียบกับไลน์ของเจ้ามือ (หรือไลน์ที่ผู้ใช้กำหนด) เพื่อหาความได้เปรียบ (edge)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import stats
from .leagues import NEGBIN, NORMAL, POISSON, SOCCER, League
from .models import GameResult, Match, Team
from .winner import Moneyline, WinnerEval, evaluate_winner

DEFAULT_ODDS = -110.0
LEAN_EDGE = 0.03     # ได้เปรียบ >= 3% -> "เอนเอียง"
STRONG_EDGE = 0.06   # ได้เปรียบ >= 6% -> "แนะนำ"
MODEL_WEIGHT = 0.4   # น้ำหนักของโมเดลเมื่อมีไลน์ตลาด (ที่เหลือเชื่อตลาด); 1.0 = ใช้โมเดลล้วน


@dataclass
class TeamForm:
    team: Team
    games: list[GameResult]
    w_for: float          # ค่าเฉลี่ยถ่วงน้ำหนัก คะแนนได้
    w_against: float      # ค่าเฉลี่ยถ่วงน้ำหนัก คะแนนเสีย
    avg_total: float      # สกอร์รวมเฉลี่ย (ไม่ถ่วงน้ำหนัก)
    last5_total: float

    @property
    def n(self) -> int:
        return len(self.games)

    @classmethod
    def from_games(cls, team: Team, games: list[GameResult], half_life: float) -> "TeamForm":
        pf = [g.points_for for g in games]
        pa = [g.points_against for g in games]
        tot = [g.total for g in games]
        nan = float("nan")
        return cls(
            team=team, games=games,
            w_for=stats.weighted_mean(pf, half_life) if games else nan,
            w_against=stats.weighted_mean(pa, half_life) if games else nan,
            avg_total=sum(tot) / len(tot) if tot else nan,
            last5_total=sum(tot[:5]) / len(tot[:5]) if tot else nan,
        )

    @classmethod
    def manual(cls, team: Team, avg_for: float, avg_against: float, n: int) -> "TeamForm":
        fake = [GameResult("", None, team.id, "", True, avg_for, avg_against)] * max(n, 0)
        tot = avg_for + avg_against
        return cls(team, fake, avg_for, avg_against, tot, tot)


@dataclass
class LineEval:
    line: float
    p_over: float
    p_under: float
    p_push: float
    over_odds: float
    under_odds: float

    def _edge(self, p: float, odds: float) -> float:
        cond = p / (1.0 - self.p_push) if self.p_push < 1 else 0.0
        return cond - 1.0 / stats.american_to_decimal(odds)

    @property
    def edge_over(self) -> float:
        return self._edge(self.p_over, self.over_odds)

    @property
    def edge_under(self) -> float:
        return self._edge(self.p_under, self.under_odds)

    @property
    def ev_over(self) -> float:
        """กำไรคาดหวังต่อเงินเดิมพัน 1 หน่วย"""
        return self.p_over * (stats.american_to_decimal(self.over_odds) - 1) - self.p_under

    @property
    def ev_under(self) -> float:
        return self.p_under * (stats.american_to_decimal(self.under_odds) - 1) - self.p_over


@dataclass
class Analysis:
    match: Match
    league: League
    home_form: TeamForm
    away_form: TeamForm
    league_avg: float
    home_exp: float
    away_exp: float
    sd: float | None
    dist: list[float] | None
    main: LineEval | None
    line_source: str
    ladder: list[LineEval]
    pick: str | None          # "over" / "under" / None
    strength: str             # "แนะนำ" / "เอนเอียง" / "ผ่าน"
    data_quality: str         # "สูง" / "ปานกลาง" / "ต่ำ"
    notes: list[str] = field(default_factory=list)
    extras: dict = field(default_factory=dict)
    winner: WinnerEval | None = None

    @property
    def total(self) -> float:
        return self.home_exp + self.away_exp

    def to_dict(self) -> dict:
        m = self.match

        def le(x: LineEval | None):
            if x is None:
                return None
            return {
                "line": x.line, "p_over": round(x.p_over, 4), "p_under": round(x.p_under, 4),
                "p_push": round(x.p_push, 4), "over_odds": x.over_odds, "under_odds": x.under_odds,
                "edge_over": round(x.edge_over, 4), "edge_under": round(x.edge_under, 4),
                "ev_over": round(x.ev_over, 4), "ev_under": round(x.ev_under, 4),
            }

        def form(f: TeamForm):
            return {"team": f.team.name, "id": f.team.id, "games": f.n,
                    "avg_for": _r(f.w_for), "avg_against": _r(f.w_against),
                    "avg_total": _r(f.avg_total), "last5_total": _r(f.last5_total)}

        return {
            "event_id": m.event_id, "league": self.league.key, "start_utc": m.start.isoformat(),
            "state": m.state, "home": m.home.name, "away": m.away.name,
            "home_form": form(self.home_form), "away_form": form(self.away_form),
            "projection": {"home": _r(self.home_exp), "away": _r(self.away_exp),
                           "total": _r(self.total), "sd": _r(self.sd)},
            "market": ({"provider": m.market.provider, "line": m.market.line,
                        "details": m.market.details} if m.market else None),
            "main_line": le(self.main), "line_source": self.line_source,
            "ladder": [le(x) for x in self.ladder],
            "pick": self.pick, "strength": self.strength, "data_quality": self.data_quality,
            "notes": self.notes, "extras": self.extras,
            "winner": self.winner.to_doc() if self.winner else None,
        }


def _r(x, nd=2):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, nd)


class TotalAnalyzer:
    def __init__(self, league: League, client=None, last_n: int = 10, half_life: float = 6.0,
                 league_avg: float | None = None, model_weight: float = MODEL_WEIGHT):
        self.league = league
        self.model_weight = min(max(model_weight, 0.0), 1.0)
        self.client = client
        self.last_n = last_n
        self.half_life = half_life
        self.league_avg = league_avg or league.team_avg

    # ---------------------------------------------------------- public ---
    def analyze(self, match: Match, line: float | None = None,
                over_odds: float | None = None, under_odds: float | None = None,
                moneyline: Moneyline | None = None) -> Analysis:
        if self.client is None:
            raise RuntimeError("ต้องมี client สำหรับดึงข้อมูล")
        hg = self.client.team_games(self.league, match.home.id, before=match.start,
                                    want=self.last_n)[: self.last_n]
        ag = self.client.team_games(self.league, match.away.id, before=match.start,
                                    want=self.last_n)[: self.last_n]
        hf = TeamForm.from_games(match.home, hg, self.half_life)
        af = TeamForm.from_games(match.away, ag, self.half_life)
        return self.evaluate(match, hf, af, line, over_odds, under_odds, moneyline)

    def evaluate(self, match: Match, hf: TeamForm, af: TeamForm, line: float | None = None,
                 over_odds: float | None = None, under_odds: float | None = None,
                 moneyline: Moneyline | None = None) -> Analysis:
        lg = self.league
        avg = self.league_avg

        h_exp, a_exp = self._project(hf, af)
        raw_total = h_exp + a_exp
        n_min = max(min(hf.n, af.n), 1)
        sd = (lg.total_sd * math.sqrt(1.0 + 1.0 / (n_min + lg.prior_games))
              if lg.model == NORMAL else None)

        # ---- ผสมกับตลาด: หาสกอร์รวมที่ไลน์+ราคาของเจ้ามือบอกไว้ แล้วถ่วงน้ำหนักกับโมเดล ----
        market = match.market
        # ไม่มีราคาเจ้ามือแต่ผู้ใช้กรอกไลน์ -> ถือว่าไลน์/ราคาที่กรอกคือตลาด
        anchor = market
        if anchor is None and line is not None:
            from .models import MarketTotal
            anchor = MarketTotal("กำหนดเอง", line, over_odds if over_odds is not None else DEFAULT_ODDS,
                                 under_odds if under_odds is not None else DEFAULT_ODDS)
        market_total = None
        if anchor is not None and self.model_weight < 1.0:
            market_total = self._market_total(h_exp, a_exp, sd, anchor)
            target = self.model_weight * raw_total + (1 - self.model_weight) * market_total
            h_exp, a_exp = h_exp * target / raw_total, a_exp * target / raw_total

        dist, probs, dh, da = self._build(h_exp, a_exp, sd)
        extras: dict = {"raw_total": round(raw_total, 2)}
        if market_total is not None:
            extras["market_total"] = round(market_total, 2)
            extras["model_weight"] = self.model_weight
        if dist is None:
            extras["proj_margin_home"] = round(h_exp - a_exp, 2)
        else:
            extras.update(self._discrete_extras(dh, da))

        # ---- ไลน์หลัก ----
        if line is not None:
            src = "กำหนดเอง"
        elif market is not None:
            line, src = market.line, f"เจ้ามือ ({market.provider})"
        else:
            line, src = None, "ไม่มีไลน์"
        oo = over_odds if over_odds is not None else (
            market.over_odds if market and market.over_odds is not None and src.startswith("เจ้ามือ")
            else DEFAULT_ODDS)
        uo = under_odds if under_odds is not None else (
            market.under_odds if market and market.under_odds is not None and src.startswith("เจ้ามือ")
            else DEFAULT_ODDS)

        def make(x, o=DEFAULT_ODDS, u=DEFAULT_ODDS):
            p_o, p_u, p_p = probs(x)
            return LineEval(x, p_o, p_u, p_p, o, u)

        main = make(line, oo, uo) if line is not None else None

        # ---- ไลน์อื่น ๆ ให้ดูประกอบ ----
        if lg.default_lines:
            ladder_lines = list(lg.default_lines)
        else:
            center = (line if line is not None else math.floor(h_exp + a_exp) + 0.5)
            ladder_lines = [center - lg.line_step, center, center + lg.line_step]
        if line is not None and line not in ladder_lines:
            ladder_lines.append(line)
        ladder = [main if (main and x == line) else make(x) for x in sorted(ladder_lines)]

        # ---- คุณภาพข้อมูล ----
        n_min = min(hf.n, af.n)
        quality = "สูง" if n_min >= 8 else "ปานกลาง" if n_min >= 4 else "ต่ำ"

        pick, strength = None, "ผ่าน"
        if main is not None:
            best = "over" if main.edge_over >= main.edge_under else "under"
            edge = max(main.edge_over, main.edge_under)
            if edge >= STRONG_EDGE:
                pick, strength = best, "แนะนำ"
            elif edge >= LEAN_EDGE:
                pick, strength = best, "เอนเอียง"
            # ข้อมูลน้อย หรือโมเดลต่างจากตลาดมากผิดปกติ -> ลดระดับความมั่นใจ
            big_gap = abs(raw_total - line) >= self._gap_threshold(sd)
            if strength == "แนะนำ" and (quality == "ต่ำ" or (anchor is not None and big_gap)):
                strength = "เอนเอียง"

        # ---- ผู้ชนะ ----
        if dist is None:
            msd = lg.margin_sd * math.sqrt(1.0 + 1.0 / (max(n_min, 1) + lg.prior_games))
            p_home = stats.norm_cdf((h_exp - a_exp) / msd) if msd > 0 else 0.5
            win_model = {"home": p_home, "away": 1 - p_home}
            extras["margin_sd"] = round(msd, 2)
        elif "p_draw" in extras:
            win_model = {"home": extras["p_home_win"], "draw": extras["p_draw"],
                         "away": extras["p_away_win"]}
        else:
            win_model = {"home": extras["p_home_win"], "away": extras["p_away_win"]}
        winner = evaluate_winner(win_model, moneyline or match.moneyline, self.model_weight, quality)

        notes = self._notes(match, hf, af, raw_total, sd, line)
        return Analysis(match, lg, hf, af, avg, h_exp, a_exp, sd, dist, main, src, ladder,
                        pick, strength, quality, notes, extras, winner)

    # --------------------------------------------------------- internals ---
    def _project(self, hf: TeamForm, af: TeamForm) -> tuple[float, float]:
        lg, avg, k = self.league, self.league_avg, self.league.prior_games

        def shrink(x, n):
            if n == 0 or math.isnan(x):
                return avg
            return (x * n + avg * k) / (n + k)

        h_off, h_def = shrink(hf.w_for, hf.n), shrink(hf.w_against, hf.n)
        a_off, a_def = shrink(af.w_for, af.n), shrink(af.w_against, af.n)
        h_exp = h_off * a_def / avg * (1.0 + lg.home_adv)
        a_exp = a_off * h_def / avg * (1.0 - lg.home_adv)
        return max(h_exp, 0.05), max(a_exp, 0.05)

    def _build(self, h_exp: float, a_exp: float, sd: float | None):
        """คืน (dist, probs(line), dist_home, dist_away) สำหรับคะแนนคาดการณ์ที่กำหนด"""
        lg = self.league
        if lg.model == NORMAL:
            return None, (lambda x: stats.normal_line_probs(h_exp + a_exp, sd, x)), None, None
        if lg.model == POISSON:
            max_k = 12
            dh = stats.distribution(lambda k: stats.poisson_pmf(k, h_exp), max_k)
            da = stats.distribution(lambda k: stats.poisson_pmf(k, a_exp), max_k)
        else:  # NEGBIN
            max_k = 30
            dh = stats.distribution(lambda k: stats.negbin_pmf(k, h_exp, lg.dispersion), max_k)
            da = stats.distribution(lambda k: stats.negbin_pmf(k, a_exp, lg.dispersion), max_k)
        dist = stats.convolve(dh, da)
        return dist, (lambda x: stats.discrete_line_probs(dist, x)), dh, da

    def _market_total(self, h_exp: float, a_exp: float, sd: float | None, market) -> float:
        """สกอร์รวมเฉลี่ยที่ทำให้โอกาส 'สูง' (ตัดค่าน้ำแล้ว) ตรงกับราคาของเจ้ามือ"""
        oo = market.over_odds if market.over_odds is not None else DEFAULT_ODDS
        uo = market.under_odds if market.under_odds is not None else DEFAULT_ODDS
        io, iu = 1 / stats.american_to_decimal(oo), 1 / stats.american_to_decimal(uo)
        target = io / (io + iu)   # P(สูง | ไม่เสมอไลน์)
        base = h_exp + a_exp
        lo, hi = 0.05, max(3.0 * market.line, base) + 10.0
        for _ in range(50):
            mid = (lo + hi) / 2
            _, probs, _, _ = self._build(h_exp * mid / base, a_exp * mid / base, sd)
            p_o, p_u, p_p = probs(market.line)
            cond = p_o / (1 - p_p) if p_p < 1 else 0.5
            if cond < target:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    def _discrete_extras(self, dh: list[float], da: list[float]) -> dict:
        p_home = sum(dh[i] * da[j] for i in range(len(dh)) for j in range(len(da)) if i > j)
        p_away = sum(dh[i] * da[j] for i in range(len(dh)) for j in range(len(da)) if j > i)
        p_draw = max(0.0, 1.0 - p_home - p_away)
        scores = sorted(((dh[i] * da[j], i, j) for i in range(min(len(dh), 8))
                         for j in range(min(len(da), 8))), reverse=True)[:5]
        out = {
            "top_scores": [{"score": f"{i}-{j}", "p": round(p, 4)} for p, i, j in scores],
            "p_home_score": round(1 - dh[0], 4),
            "p_away_score": round(1 - da[0], 4),
        }
        if self.league.sport == SOCCER:
            out.update({
                "p_home_win": round(p_home, 4), "p_draw": round(p_draw, 4),
                "p_away_win": round(p_away, 4),
                "p_btts": round((1 - dh[0]) * (1 - da[0]), 4),
            })
        else:  # เบสบอลไม่มีเสมอ -> ตัดกรณีเท่ากันออก (ต่อเวลา)
            s = p_home + p_away
            out.update({"p_home_win": round(p_home / s, 4) if s else None,
                        "p_away_win": round(p_away / s, 4) if s else None})
        return out

    def _gap_threshold(self, sd: float | None) -> float:
        """ส่วนต่างระหว่างโมเดลกับไลน์ที่ถือว่า "มากผิดปกติ" """
        if sd:
            return sd * 0.6
        return 0.8 if self.league.sport == SOCCER else 2.0

    def _notes(self, match, hf, af, total, sd, line) -> list[str]:
        lg = self.league
        notes = []
        for f in (hf, af):
            if f.n == 0:
                notes.append(f"ไม่พบผลการแข่งขันของ {f.team.name} — ใช้ค่าเฉลี่ยลีกแทนทั้งหมด")
            elif f.n < 4:
                notes.append(f"{f.team.name} มีข้อมูลเพียง {f.n} นัด ผลวิเคราะห์อาจคลาดเคลื่อนสูง")
            if f.n >= 6 and not math.isnan(f.avg_total) and f.avg_total > 0:
                diff = (f.last5_total - f.avg_total) / f.avg_total
                if abs(diff) >= 0.10:
                    word = "สูงกว่า" if diff > 0 else "ต่ำกว่า"
                    notes.append(f"5 นัดหลังสุดของ {f.team.name} สกอร์รวมเฉลี่ย {f.last5_total:.1f} "
                                 f"{word}ค่าเฉลี่ยช่วงที่ดู ({f.avg_total:.1f}) {abs(diff):.0%}")
        if line is not None:
            gap = total - line
            if abs(gap) >= self._gap_threshold(sd):
                hint = {"baseball": "ผู้ขว้างตัวจริง, สนาม, สภาพอากาศ/ลม",
                        "football": "ผู้เล่นเจ็บ (โดยเฉพาะ QB), สภาพอากาศ",
                        "soccer": "ตัวจริง/การหมุนเวียนผู้เล่น, เกมถ้วยกลางสัปดาห์",
                        }.get(lg.sport, "ผู้เล่นเจ็บ/พัก, แข่งติดกันสองวัน (back-to-back)")
                notes.append(f"โมเดลต่างจากไลน์ {gap:+.1f} {lg.unit_th} ซึ่งถือว่ามาก — "
                             f"ตลาดอาจรู้ข่าวที่โมเดลไม่เห็น ({hint})")
        if lg.model == NEGBIN:
            notes.append("โมเดลยังไม่รวมข้อมูลผู้ขว้างตัวจริง (starting pitcher) ควรตรวจสอบประกอบ")
        if not match.is_pregame:
            notes.append(f"นัดนี้สถานะ '{match.status_detail}' ไม่ใช่ก่อนเริ่มเกม")
        return notes
