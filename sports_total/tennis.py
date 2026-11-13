"""เทนนิส ATP / WTA: ดึงข้อมูลจาก ESPN, คำนวณ Elo, วิเคราะห์ผู้ชนะและจำนวนเกมรวม

แหล่งข้อมูล: scoreboard ของ ESPN ตามวันที่ ได้ทุกแมตช์ของรายการที่แข่งวันนั้น (เฉพาะระดับทัวร์;
ไม่มี Challenger / WTA 125 และไม่มีราคาเจ้ามือ)

ขั้นตอน
1. ไล่ดึงผลย้อนหลัง 52 สัปดาห์ (วันพุธของทุกสัปดาห์ ครอบคลุมรายการที่แข่งสัปดาห์นั้น)
2. Elo ของผู้เล่นทุกคนตามลำดับเวลา -> โอกาสชนะ
3. เกมต่อเซตของผู้เล่น (สะท้อนความแรงของเสิร์ฟ) -> ระดับเสิร์ฟพื้นฐานของแมตช์
4. ลูกโซ่มาร์คอฟ (tennis_model) -> โอกาสชนะ, การกระจายจำนวนเกมรวม, สกอร์เซต
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from . import stats, tennis_model as tm
from .espn import FetchError, parse_dt
from .leagues import League
from .models import Match, Team
from .winner import Moneyline, WinnerEval, evaluate_winner

US_EAST = timezone(timedelta(hours=-5))
DEFAULT_ODDS = -110.0
ELO_START = 1500.0
SET_PRIOR = 20.0        # น้ำหนักค่าเฉลี่ยทัวร์ของ "เกมต่อเซต" (จำนวนเซตเสมือน)

# ค่าปรับเทียบ (ทดสอบนอกช่วง: เรตติ้งก่อน 14 ก.ย. 2026 ทาย ~1,500 แมตช์หลังจากนั้น)
# - ELO_SCALE: Elo จากข้อมูลปีเดียวมั่นใจเกินจริง ย่อส่วนต่างลง (log loss ดีที่สุดที่ ~0.6)
# - TOTAL_DMULT/TOTAL_SHIFT: แมตช์จริงมีเซตขาดลอยมากกว่าโมเดลแต้มอิสระ จึงขยายความต่างฝีมือ
#   สำหรับการกระจายจำนวนเกม และเลื่อนลง เพื่อให้โอกาส สูง/ต่ำ ที่ไลน์กลางตรงกับผลจริง
ELO_SCALE = 0.6
TOTAL_DMULT = 1.5
TOTAL_SHIFT = {"atp": -2.0, "wta": -2.5}


@dataclass
class TMatch:
    id: str
    start: datetime
    state: str
    status: str
    event: str
    round: str
    best_of: int
    a: Team
    b: Team
    a_rank: int | None
    b_rank: int | None
    sets: list[tuple[int, int]]
    winner: str | None          # "a" / "b"
    clean: bool                 # จบครบ ไม่มีถอนตัว/ชนะบาย
    venue: str = ""


def _player(c: dict) -> tuple[Team, int | None]:
    ath = c.get("athlete") or {}
    rank = (c.get("curatedRank") or {}).get("current")
    return (Team(id=str(c.get("id") or ""), name=ath.get("displayName") or "TBD",
                 abbr=(ath.get("flag") or {}).get("alt") or ""),
            rank if isinstance(rank, int) and rank < 99 else None)


SLAMS = ("australian open", "roland garros", "french open", "wimbledon", "us open")


def best_of_for(tour: str, event: str) -> int:
    """ESPN ระบุจำนวนเซตไม่ตรง (ATP มักเป็น 5 ทุกรายการ) จึงใช้กติกาจริง:
    แกรนด์สแลมชาย 5 เซต นอกนั้น 3 เซต"""
    return 5 if tour == "atp" and any(k in event.lower() for k in SLAMS) else 3


def parse_day(data: dict, tour: str = "atp") -> list[TMatch]:
    out = []
    for ev in data.get("events") or []:
        for grp in ev.get("groupings") or []:
            gname = ((grp.get("grouping") or {}).get("displayName") or "")
            want = "Women's Singles" if tour == "wta" else "Men's Singles"
            if gname != want:   # รายการร่วมชาย/หญิง (เช่น แกรนด์สแลม) มีทั้งสองประเภทในฟีดเดียวกัน
                continue
            for c in grp.get("competitions") or []:
                try:
                    comps = sorted(c.get("competitors") or [], key=lambda x: x.get("order", 0))
                    if len(comps) != 2:
                        continue
                    (a, ar), (b, br) = _player(comps[0]), _player(comps[1])
                    st = (c.get("status") or {}).get("type") or {}
                    start = parse_dt(c.get("date") or c.get("startDate"))
                    if start is None:
                        continue
                    la = comps[0].get("linescores") or []
                    lb = comps[1].get("linescores") or []
                    sets = [(int(x.get("value") or 0), int(y.get("value") or 0)) for x, y in zip(la, lb)]
                    winner = "a" if comps[0].get("winner") else "b" if comps[1].get("winner") else None
                    note = " ".join(n.get("text", "") for n in c.get("notes") or []).lower()
                    best_of = best_of_for(tour, ev.get("name") or "")
                    won = max(sum(x > y for x, y in sets), sum(y > x for x, y in sets))
                    if st.get("completed") and won in (2, 3):
                        best_of = 3 if won == 2 else 5
                    clean = (st.get("completed", False) and winner is not None and won in (2, 3)
                             and all(max(x, y) >= 6 for x, y in sets)
                             and not any(k in note for k in ("ret.", "retired", "w/o", "walkover", "def.")))
                    out.append(TMatch(
                        id=str(c.get("id")), start=start, state=st.get("state") or "",
                        status=st.get("shortDetail") or st.get("detail") or "",
                        event=ev.get("name") or "", round=(c.get("round") or {}).get("displayName") or "",
                        best_of=best_of, a=a, b=b, a_rank=ar, b_rank=br,
                        sets=sets, winner=winner, clean=clean,
                        venue=(c.get("venue") or {}).get("fullName") or ""))
                except Exception:
                    continue
    return out


@dataclass
class PlayerStats:
    elo: float = ELO_START
    n: int = 0
    wins: int = 0
    sets: int = 0
    games: int = 0
    recent: list[str] = field(default_factory=list)   # "W"/"L" ล่าสุดก่อน

    @property
    def gps(self) -> float:
        return self.games / self.sets if self.sets else float("nan")


class TennisSource:
    def __init__(self, http):
        self.http = http
        self._ratings: dict[tuple[str, str], tuple[dict, float]] = {}

    def day(self, league: League, d: date, ttl: int) -> list[TMatch]:
        url = (f"https://site.api.espn.com/apis/site/v2/sports/tennis/{league.slug}/scoreboard"
               f"?dates={d:%Y%m%d}")
        return parse_day(self.http.fetch_url(url, ttl), league.slug)

    # ---- ใช้ร่วมกับ CLI เดิม (games / analyze) ----
    def scoreboard(self, league: League, day: date | None = None, days: int = 1) -> list[Match]:
        day = day or datetime.now(US_EAST).date()
        seen, out = set(), []
        for i in range(max(days, 1)):
            d = day + timedelta(days=i)
            for t in self.day(league, d, ttl=300):
                if t.id in seen or t.start.astimezone(US_EAST).date() != d:
                    continue
                if not t.a.id or not t.b.id or "TBD" in (t.a.name, t.b.name):
                    continue   # คู่แข่งยังไม่รู้ (รอผลรอบก่อน)
                seen.add(t.id)
                out.append(to_match(t, league))
        return sorted(out, key=lambda m: m.start)

    def team_games(self, *a, **k):
        return []

    def history(self, league: League, before: datetime, weeks: int = 52) -> list[TMatch]:
        today = datetime.now(US_EAST).date()
        d = before.astimezone(US_EAST).date()
        d -= timedelta(days=(d.weekday() - 2) % 7)        # วันพุธล่าสุด
        seen: dict[str, TMatch] = {}
        for _ in range(weeks):
            ttl = 3600 if (today - d).days < 10 else 30 * 86400
            try:
                for t in self.day(league, d, ttl):
                    if t.clean and t.start < before:
                        seen[t.id] = t
            except FetchError:
                pass
            d -= timedelta(days=7)
        return sorted(seen.values(), key=lambda t: t.start)

    def ratings(self, league: League, before: datetime) -> tuple[dict[str, PlayerStats], float]:
        """Elo + สถิติเกม ของผู้เล่นทุกคน และค่าเฉลี่ยเกมต่อเซตของทัวร์"""
        key = (league.key, before.strftime("%Y%m%d"))
        if key not in self._ratings:
            players: dict[str, PlayerStats] = {}
            tg = ts = 0
            for t in self.history(league, before):
                pa = players.setdefault(t.a.id, PlayerStats())
                pb = players.setdefault(t.b.id, PlayerStats())
                ea = 1 / (1 + 10 ** ((pb.elo - pa.elo) / 400))
                sa = 1.0 if t.winner == "a" else 0.0
                ka, kb = 250 / (pa.n + 5) ** 0.4, 250 / (pb.n + 5) ** 0.4
                pa.elo += ka * (sa - ea)
                pb.elo += kb * ((1 - sa) - (1 - ea))
                g = sum(x + y for x, y in t.sets)
                for p, won in ((pa, sa == 1), (pb, sa == 0)):
                    p.n += 1
                    p.wins += won
                    p.sets += len(t.sets)
                    p.games += g
                    p.recent.insert(0, "W" if won else "L")
                    del p.recent[10:]
                tg += g
                ts += len(t.sets)
            self._ratings[key] = (players, tg / ts if ts else league.team_avg)
        return self._ratings[key]


def to_match(t: TMatch, league: League) -> Match:
    m = Match(event_id=t.id, league_key=league.key, start=t.start, state=t.state,
              status_detail=t.status, home=t.a, away=t.b, venue=t.venue)
    m.home.record = f"มือวาง {t.a_rank}" if t.a_rank else ""
    m.away.record = f"มือวาง {t.b_rank}" if t.b_rank else ""
    m.info = {"event": t.event, "round": t.round, "best_of": t.best_of}
    return m


# ------------------------------------------------------------------ analysis ---

@dataclass
class TennisAnalysis:
    match: Match
    league: League
    pa_stats: PlayerStats
    pb_stats: PlayerStats
    best_of: int
    res: dict                       # ผลจากโมเดลมาร์คอฟ (หลังผสมตลาดสกอร์รวม)
    raw_total: float
    market_total: float | None
    dist: list[float]
    main: object | None             # analyzer.LineEval
    ladder: list
    pick: str | None
    strength: str
    quality: str
    winner: WinnerEval
    notes: list[str]

    @property
    def total(self) -> float:
        return sum(i * p for i, p in enumerate(self.dist))


class TennisAnalyzer:
    def __init__(self, league: League, client, model_weight: float = 0.4):
        self.league = league
        self.client = client
        self.src: TennisSource = client._source(league)
        self.model_weight = model_weight

    def analyze(self, match: Match, line: float | None = None, over_odds: float | None = None,
                under_odds: float | None = None, moneyline: Moneyline | None = None) -> TennisAnalysis:
        from .analyzer import LineEval
        players, tour_gps = self.src.ratings(self.league, match.start)
        a = players.get(match.home.id, PlayerStats())
        b = players.get(match.away.id, PlayerStats())
        best_of = (getattr(match, "info", None) or {}).get("best_of", 3)

        p_elo = 1 / (1 + 10 ** (-(a.elo - b.elo) * ELO_SCALE / 400))

        def shrunk(p: PlayerStats) -> float:
            return (p.games + tour_gps * SET_PRIOR) / (p.sets + SET_PRIOR)

        # เกมต่อเซตของคู่นี้ เทียบกับค่าเฉลี่ยทัวร์ -> ปรับระดับเสิร์ฟพื้นฐานของทัวร์
        ref = tm.games_per_set(self.league.team_avg)          # team_avg = โอกาสแต้มเสิร์ฟเฉลี่ยของทัวร์
        target = ref + (shrunk(a) + shrunk(b)) / 2 - tour_gps
        res = tm.solve_match(p_elo, target, best_of)        # โอกาสชนะ (ปรับตามจำนวนเซตแล้ว)
        tot = totals_model(res, best_of, TOTAL_SHIFT.get(self.league.key, -2.0))
        raw_dist, raw_total = tot["dist"], tot["e_total"]
        res = dict(res, sets=tot["sets"], e_ga=tot["e_ga"], e_gb=tot["e_gb"])

        # ---- สกอร์รวมเกม: ผสมกับไลน์ที่ผู้ใช้กรอก (ESPN ไม่มีราคาเทนนิส) ----
        dist, market_total = raw_dist, None
        if line is not None and self.model_weight < 1:
            oo = over_odds if over_odds is not None else DEFAULT_ODDS
            uo = under_odds if under_odds is not None else DEFAULT_ODDS
            market_total = market_total_shift(raw_dist, line, oo, uo)
            blended = self.model_weight * raw_total + (1 - self.model_weight) * market_total
            dist = tm.shift_dist(raw_dist, blended - raw_total)

        def make(x, o=DEFAULT_ODDS, u=DEFAULT_ODDS):
            po, pu, pp = stats.discrete_line_probs(dist, x)
            return LineEval(x, po, pu, pp, o, u)

        main = make(line, over_odds or DEFAULT_ODDS, under_odds or DEFAULT_ODDS) if line is not None else None
        center = line if line is not None else math.floor(raw_total) + 0.5
        step = 3.0 if best_of == 5 else 2.0
        ladder = sorted({center - step, center, center + step} | ({line} if line is not None else set()))
        ladder = [main if (main and x == line) else make(x) for x in ladder]

        n_min = min(a.n, b.n)
        quality = "สูง" if n_min >= 15 else "ปานกลาง" if n_min >= 5 else "ต่ำ"
        pick, strength = None, "ผ่าน"
        if main is not None:
            best = "over" if main.edge_over >= main.edge_under else "under"
            edge = max(main.edge_over, main.edge_under)
            if edge >= 0.06:
                pick, strength = best, "แนะนำ"
            elif edge >= 0.03:
                pick, strength = best, "เอนเอียง"
            if strength == "แนะนำ" and (quality == "ต่ำ" or abs(raw_total - line) >= 3):
                strength = "เอนเอียง"

        winner = evaluate_winner({"home": res["p_a"], "away": 1 - res["p_a"]}, moneyline,
                                 self.model_weight, quality)

        notes = []
        for p, t in ((a, match.home), (b, match.away)):
            if p.n == 0:
                notes.append(f"ไม่พบผลแข่งระดับทัวร์ของ {t.name} ใน 52 สัปดาห์ (อาจมาจาก Challenger/ITF) — ใช้ Elo เริ่มต้น")
            elif p.n < 5:
                notes.append(f"{t.name} มีผลแข่งระดับทัวร์เพียง {p.n} แมตช์ ผลอาจคลาดเคลื่อนสูง")
        notes.append("โมเดลยังไม่แยกพื้นสนาม (ฮาร์ด/ดิน/หญ้า) และไม่รู้อาการบาดเจ็บ")
        if not match.is_pregame:
            notes.append(f"แมตช์นี้สถานะ '{match.status_detail}' ไม่ใช่ก่อนเริ่ม")

        res = dict(res, p_elo=p_elo, tour_gps=tour_gps)
        return TennisAnalysis(match, self.league, a, b, best_of, res, raw_total, market_total, dist,
                              main, ladder, pick, strength, quality, winner, notes)


def totals_model(res: dict, best_of: int, shift: float) -> dict:
    """การกระจายจำนวนเกมหลังปรับเทียบ: ขยายความต่างฝีมือ x TOTAL_DMULT แล้วเลื่อน shift เกม"""
    base, d = res["base"], (res["pa"] - res["pb"]) / 2 * TOTAL_DMULT
    d = max(min(d, base - 0.36, 0.94 - base), -(base - 0.36), -(0.94 - base))
    r = tm.match_result(round(base + d, 5), round(base - d, 5), best_of)
    dist = tm.shift_dist(r["dist"], shift)
    return {"dist": dist, "e_total": sum(i * p for i, p in enumerate(dist)), "sets": r["sets"],
            "e_ga": r["e_ga"] + shift / 2, "e_gb": r["e_gb"] + shift / 2}


def market_total_shift(dist: list[float], line: float, oo: float, uo: float) -> float:
    """ค่าเฉลี่ยจำนวนเกมที่ไลน์+ราคาบอกไว้ (เลื่อนการกระจายของโมเดลจนโอกาส 'สูง' ตรงกับราคา)"""
    io, iu = 1 / stats.american_to_decimal(oo), 1 / stats.american_to_decimal(uo)
    target = io / (io + iu)
    base = sum(i * p for i, p in enumerate(dist))

    def p_over(delta):
        po, pu, pp = stats.discrete_line_probs(tm.shift_dist(dist, delta), line)
        return po / (1 - pp) if pp < 1 else 0.5

    delta = tm._bisect(p_over, -15.0, 15.0, target, 40)
    return base + delta


# ------------------------------------------------------------------- output ---

def render(a: TennisAnalysis) -> str:
    from .report import TH_TZ, fmt_odds, render_winner, _line_row
    m = a.match
    info = getattr(m, "info", {}) or {}
    out = ["=" * 72, f"เทนนิส | {a.league.name_th} | {info.get('event', '')} — {info.get('round', '')}",
           f"{m.home.name} ({m.home.abbr}{' ' + m.home.record if m.home.record else ''})  vs  "
           f"{m.away.name} ({m.away.abbr}{' ' + m.away.record if m.away.record else ''})",
           f"เวลาแข่ง: {m.start.astimezone(TH_TZ):%d/%m/%Y %H:%M} น. (เวลาไทย) · แข่ง {a.best_of} เซต",
           "-" * 72, "ฟอร์ม 52 สัปดาห์ (ระดับทัวร์)"]
    for p, t in ((a.pa_stats, m.home), (a.pb_stats, m.away)):
        wp = f"{p.wins / p.n:.0%}" if p.n else "-"
        gps = f"{p.gps:.2f}" if p.sets else "-"
        out.append(f" • {t.name}: Elo {p.elo:.0f} | {p.n} แมตช์ ชนะ {wp} | เกม/เซต {gps} | "
                   f"ล่าสุด {''.join(p.recent[:10]) or '-'}")
    r = a.res
    out += ["-" * 72, "ผลคาดการณ์",
            f"   เกมที่คาดว่าแต่ละฝ่ายได้: {m.home.name} {r['e_ga']:.1f} / {m.away.name} {r['e_gb']:.1f}",
            f"   จำนวนเกมรวมคาดการณ์: {a.total:.1f} เกม"]
    if a.market_total is not None:
        out.append(f"   (โมเดลล้วน {a.raw_total:.1f} · ไลน์ที่กรอกบอก {a.market_total:.1f} · ผสม 40%/60%)")
    sets = sorted(r["sets"].items(), key=lambda kv: -kv[1])
    out.append("   สกอร์เซต (ผู้เล่นแรก-ผู้เล่นหลัง): " + ", ".join(f"{k} {v:.0%}" for k, v in sets))
    out += ["-" * 72, "เทียบไลน์จำนวนเกมรวม"]
    if a.main is None:
        out.append("   ไม่มีราคาเจ้ามือ — ใช้ --line เพื่อกำหนดเอง (แสดงไลน์อ้างอิงด้านล่าง)")
    for x in a.ladder:
        out.append(_line_row(x, "เกม") + ("  ◀ หลัก" if a.main is x else ""))
    if a.pick:
        out.append(f"สรุปสกอร์รวม: {a.strength} {'สูง' if a.pick == 'over' else 'ต่ำ'} {a.main.line:g}")
    out += ["-" * 72] + render_winner(a.winner, {"home": m.home.name, "away": m.away.name})
    out.append(f"ความน่าเชื่อถือของข้อมูล: {a.quality}")
    out += [f" ⚠ {n}" for n in a.notes]
    return "\n".join(out)


def to_doc(a: TennisAnalysis) -> dict:
    from .export import _line, _r, _trim_dist
    m = a.match
    info = getattr(m, "info", {}) or {}

    def player(t: Team, p: PlayerStats) -> dict:
        return {"name": t.name, "abbr": t.abbr, "record": t.record, "n": p.n,
                "elo": round(p.elo), "win_pct": _r(p.wins / p.n, 3) if p.n else None,
                "gps": _r(p.gps, 2) if p.sets else None, "recent": "".join(p.recent[:10])}

    r = a.res
    return {
        "id": m.event_id, "start": m.start.astimezone(timezone.utc).isoformat(),
        "status": m.status_detail, "venue": m.venue, "event": info.get("event", ""),
        "round": info.get("round", ""), "best_of": a.best_of,
        "home": player(m.home, a.pa_stats), "away": player(m.away, a.pb_stats),
        "proj": {"home": _r(r["e_ga"], 2), "away": _r(r["e_gb"], 2), "total": _r(a.total, 2), "sd": None},
        "dist": _trim_dist(a.dist), "market": None, "main": _line(a.main),
        "line_source": "กำหนดเอง" if a.main else "ไม่มีไลน์",
        "pick": a.pick, "strength": a.strength, "quality": a.quality, "notes": a.notes,
        "extras": {"raw_total": _r(a.raw_total, 2), "sets": {k: _r(v, 4) for k, v in r["sets"].items()},
                   "p_home_win": _r(r["p_a"], 4), "p_away_win": _r(1 - r["p_a"], 4),
                   "elo_diff": round(a.pa_stats.elo - a.pb_stats.elo), "serve_a": _r(r["pa"], 4),
                   "serve_b": _r(r["pb"], 4), "tour_gps": _r(r["tour_gps"], 3)},
        "winner": a.winner.to_doc(),
    }
