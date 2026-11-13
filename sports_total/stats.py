"""ฟังก์ชันสถิติพื้นฐาน (ใช้ไลบรารีมาตรฐานเท่านั้น)"""

from __future__ import annotations

import math


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(k * math.log(lam) - lam - math.lgamma(k + 1))


def negbin_pmf(k: int, mu: float, r: float) -> float:
    """ทวินามลบแบบ mean/dispersion: Var = mu + mu^2 / r"""
    if mu <= 0:
        return 1.0 if k == 0 else 0.0
    p = r / (r + mu)
    return math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
                    + r * math.log(p) + k * math.log(1 - p))


def distribution(pmf, max_k: int) -> list[float]:
    d = [pmf(k) for k in range(max_k + 1)]
    s = sum(d)
    return [x / s for x in d] if s > 0 else d


def convolve(a: list[float], b: list[float]) -> list[float]:
    out = [0.0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        if x == 0:
            continue
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out


def is_whole(line: float) -> bool:
    return abs(line - round(line)) < 1e-9


def discrete_line_probs(dist: list[float], line: float) -> tuple[float, float, float]:
    """คืนค่า (P สูง, P ต่ำ, P เสมอไลน์/คืนเงิน)"""
    over = sum(p for k, p in enumerate(dist) if k > line + 1e-9)
    push = dist[int(round(line))] if is_whole(line) and 0 <= round(line) < len(dist) else 0.0
    return over, max(0.0, 1.0 - over - push), push


def normal_line_probs(mu: float, sd: float, line: float) -> tuple[float, float, float]:
    """ใช้ continuity correction เพราะคะแนนจริงเป็นจำนวนเต็ม"""
    if is_whole(line):
        over = 1.0 - norm_cdf((line + 0.5 - mu) / sd)
        under = norm_cdf((line - 0.5 - mu) / sd)
        return over, under, max(0.0, 1.0 - over - under)
    over = 1.0 - norm_cdf((line - mu) / sd)
    return over, 1.0 - over, 0.0


def american_to_decimal(odds: float) -> float:
    if odds >= 100:
        return 1.0 + odds / 100.0
    if odds <= -100:
        return 1.0 + 100.0 / abs(odds)
    return 2.0  # ค่าแปลก ๆ ถือว่าราคาเท่ากัน


def weighted_mean(values: list[float], half_life: float) -> float:
    """ค่าเฉลี่ยถ่วงน้ำหนักแบบลดลงเชิงเลขชี้กำลัง (values เรียงจากล่าสุด -> เก่าสุด)"""
    if not values:
        return float("nan")
    if half_life <= 0:
        return sum(values) / len(values)
    w = [0.5 ** (i / half_life) for i in range(len(values))]
    return sum(v * x for v, x in zip(values, w)) / sum(w)
