"""โมเดลเทนนิสแบบลูกโซ่มาร์คอฟ: แต้ม -> เกม -> เซต -> แมตช์

ใส่โอกาสได้แต้มเมื่อเป็นฝ่ายเสิร์ฟของผู้เล่น A (pa) และ B (pb) แล้วได้
- โอกาสชนะแมตช์
- การกระจายของจำนวนเกมรวม (ใช้กับไลน์สกอร์รวมเกม)
- โอกาสสกอร์เซต (2-0, 2-1, ...) และจำนวนเกมคาดหวังของแต่ละฝ่าย

กติกา: เซตละ 6 เกม ไทเบรกที่ 6-6 (นับเป็น 7-6, รวม 13 เกม) ทุกเซตรวมเซตสุดท้าย
"""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache


def hold_prob(p: float) -> float:
    """โอกาสชนะเกมเสิร์ฟของตัวเอง เมื่อได้แต้มเสิร์ฟด้วยโอกาส p"""
    q = 1.0 - p
    deuce = p * p / (1.0 - 2.0 * p * q)
    return p ** 4 * (1 + 4 * q + 10 * q * q) + 20 * p ** 3 * q ** 3 * deuce


def tiebreak_prob(pa: float, pb: float) -> float:
    """โอกาสที่ A ชนะไทเบรก เมื่อ A เสิร์ฟแต้มแรก (ลำดับเสิร์ฟ A, B, B, A, A, ...)"""
    num = pa * (1 - pb)
    tie = num / (num + (1 - pa) * pb)

    @lru_cache(maxsize=None)
    def f(a: int, b: int) -> float:
        if a == 7 and b <= 5:
            return 1.0
        if b == 7 and a <= 5:
            return 0.0
        if a == 6 and b == 6:
            return tie
        a_serves = (a + b) % 4 in (0, 3)
        p = pa if a_serves else 1 - pb
        return p * f(a + 1, b) + (1 - p) * f(a, b + 1)

    return f(0, 0)


@lru_cache(maxsize=4096)
def set_outcomes(pa: float, pb: float, a_first: bool) -> tuple[tuple[int, int, float], ...]:
    """การกระจายสกอร์ของหนึ่งเซต: ((เกม A, เกม B, โอกาส), ...)"""
    ha, hb = hold_prob(pa), hold_prob(pb)
    dp: dict[tuple[int, int], float] = defaultdict(float)
    dp[(0, 0)] = 1.0
    out: dict[tuple[int, int], float] = defaultdict(float)
    for g in range(13):
        for ga in range(g + 1):
            gb = g - ga
            pr = dp.get((ga, gb), 0.0)
            if not pr:
                continue
            if (ga >= 6 or gb >= 6) and abs(ga - gb) >= 2:
                out[(ga, gb)] += pr
                continue
            if ga == 6 and gb == 6:
                # ผู้เสิร์ฟเกมที่ 13 (index 12) คือผู้ที่เสิร์ฟก่อนในเซต
                p_tb = tiebreak_prob(pa, pb) if a_first else 1 - tiebreak_prob(pb, pa)
                out[(7, 6)] += pr * p_tb
                out[(6, 7)] += pr * (1 - p_tb)
                continue
            a_serves = (g % 2 == 0) == a_first
            pw = ha if a_serves else 1 - hb
            dp[(ga + 1, gb)] += pr * pw
            dp[(ga, gb + 1)] += pr * (1 - pw)
    return tuple((ga, gb, p) for (ga, gb), p in out.items())


def match_result(pa: float, pb: float, best_of: int = 3) -> dict:
    """ผลรวมของแมตช์ (สุ่มผู้เสิร์ฟก่อน 50/50)"""
    need = (best_of + 1) // 2
    so = {True: set_outcomes(pa, pb, True), False: set_outcomes(pa, pb, False)}
    states: dict[tuple[int, int, bool], dict[int, float]] = {
        (0, 0, True): {0: 0.5}, (0, 0, False): {0: 0.5}}
    total: dict[int, float] = defaultdict(float)
    sets_score: dict[str, float] = defaultdict(float)
    p_a = e_ga = e_gb = 0.0
    for k in range(2 * need - 1):
        for (sa, sb, first), dist in [(s, d) for s, d in states.items() if s[0] + s[1] == k]:
            mass = sum(dist.values())
            for ga, gb, p in so[first]:
                e_ga += mass * p * ga
                e_gb += mass * p * gb
                t = ga + gb
                nfirst = first if t % 2 == 0 else not first
                nsa, nsb = sa + (ga > gb), sb + (gb > ga)
                done = nsa == need or nsb == need
                if done:
                    target = total
                    sets_score[f"{nsa}-{nsb}"] += mass * p
                    if nsa == need:
                        p_a += mass * p
                else:
                    target = states.setdefault((nsa, nsb, nfirst), defaultdict(float))
                for tot, q in dist.items():
                    target[tot + t] += q * p
    size = max(total) + 1
    dist = [total.get(i, 0.0) for i in range(size)]
    return {"p_a": p_a, "dist": dist, "sets": dict(sets_score), "e_ga": e_ga, "e_gb": e_gb,
            "e_total": sum(i * p for i, p in enumerate(dist))}


def games_per_set(p: float) -> float:
    """จำนวนเกมเฉลี่ยต่อเซต เมื่อสองฝ่ายเก่งเท่ากัน (โอกาสแต้มเสิร์ฟ p)"""
    return sum((ga + gb) * pr for ga, gb, pr in set_outcomes(round(p, 4), round(p, 4), True))


def _bisect(f, lo: float, hi: float, target: float, it: int = 40) -> float:
    """หา x ที่ f(x) = target โดย f เพิ่มขึ้นตาม x"""
    for _ in range(it):
        mid = (lo + hi) / 2
        if f(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


@lru_cache(maxsize=512)
def base_for_gps(gps: float) -> float:
    """ระดับเสิร์ฟพื้นฐานที่ทำให้เกมต่อเซตเท่ากับ gps (ยิ่งเสิร์ฟดี ยิ่งหลายเกม)"""
    gps = min(max(gps, 9.0), 11.5)
    return _bisect(games_per_set, 0.50, 0.80, gps, 30)


def solve_match(p_win_bo3: float, gps: float, best_of: int = 3) -> dict:
    """หาโอกาสแต้มเสิร์ฟของสองฝ่ายให้ตรงกับโอกาสชนะ (ในแมตช์ 3 เซต) และระดับเกมต่อเซต
    แล้วคืนผลของแมตช์ตามจำนวนเซตจริง"""
    base = base_for_gps(round(gps, 2))
    p = min(max(p_win_bo3, 0.02), 0.98)
    span = min(base - 0.35, 0.95 - base, 0.2)

    def win(d):
        d = round(d, 5)
        return match_result(round(base + d, 5), round(base - d, 5), 3)["p_a"]

    d = _bisect(win, -span, span, p, 30)
    res = match_result(round(base + d, 5), round(base - d, 5), best_of)
    res.update({"pa": base + d, "pb": base - d, "base": base})
    return res


def shift_dist(dist: list[float], delta: float) -> list[float]:
    """เลื่อนการกระจายไปทางขวา delta หน่วย (เศษส่วนใช้การประมาณเชิงเส้น)"""
    n = len(dist) + int(abs(delta)) + 2
    out = [0.0] * n
    for k, p in enumerate(dist):
        x = k + delta
        lo = int(x // 1)
        frac = x - lo
        for idx, w in ((lo, 1 - frac), (lo + 1, frac)):
            idx = min(max(idx, 0), n - 1)
            out[idx] += p * w
    s = sum(out)
    return [p / s for p in out] if s else out
