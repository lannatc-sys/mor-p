"""แสดงผลเป็นข้อความภาษาไทย"""

from __future__ import annotations

import math
from datetime import timedelta, timezone

from .analyzer import Analysis, LineEval
from .leagues import NORMAL, SOCCER
from .models import Match

try:
    from zoneinfo import ZoneInfo
    TH_TZ = ZoneInfo("Asia/Bangkok")
except Exception:  # Windows ที่ไม่มี tzdata
    TH_TZ = timezone(timedelta(hours=7))

PICK_TH = {"over": "สูง (Over)", "under": "ต่ำ (Under)"}


def th_time(m: Match) -> str:
    return m.start.astimezone(TH_TZ).strftime("%d/%m/%Y %H:%M") + " น. (เวลาไทย)"


def fmt_num(x, nd=1) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def fmt_odds(o: float | None) -> str:
    if o is None:
        return "-"
    return f"+{o:.0f}" if o > 0 else f"{o:.0f}"


def match_line(m: Match) -> str:
    mk = m.market
    mk_s = f" | ไลน์สกอร์รวม {mk.line:g} ({mk.provider})" if mk else ""
    score = ""
    if m.state in ("in", "post") and m.home_score is not None:
        score = f" [{m.away_score:g}-{m.home_score:g}]"
    return (f"[{m.event_id}] {th_time(m)}  {m.away.name} @ {m.home.name}"
            f"{score}  ({m.status_detail or m.state}){mk_s}")


def _line_row(x: LineEval, unit: str) -> str:
    push = f"  เสมอไลน์ {x.p_push:5.1%}" if x.p_push > 0.0005 else ""
    return (f"   ไลน์ {x.line:>6g} {unit}:  สูง {x.p_over:5.1%}  ต่ำ {x.p_under:5.1%}{push}"
            f"   | edge สูง {x.edge_over:+.1%}  ต่ำ {x.edge_under:+.1%}")


def render(a: Analysis) -> str:
    m, lg = a.match, a.league
    u = lg.unit_th
    out = []
    bar = "=" * 72
    out.append(bar)
    out.append(f"{lg.sport_th} | {lg.name_th}")
    out.append(f"{m.away.name} (เยือน) @ {m.home.name} (เหย้า)")
    out.append(f"เวลาแข่ง: {th_time(m)}   สถานะ: {m.status_detail or m.state}")
    if m.venue:
        out.append(f"สนาม: {m.venue}")
    out.append("-" * 72)

    out.append(f"ฟอร์มทีม (สูงสุด {max(a.home_form.n, a.away_form.n)} นัดล่าสุด, ถ่วงน้ำหนักเกมล่าสุด)")
    for side, f in (("เหย้า", a.home_form), ("เยือน", a.away_form)):
        rec = f" สถิติ {f.team.record}" if f.team.record else ""
        out.append(f" • {f.team.name} [{side}]{rec}")
        out.append(f"     {f.n} นัด | ได้ {fmt_num(f.w_for)} เสีย {fmt_num(f.w_against)} {u}/เกม"
                   f" | สกอร์รวมเฉลี่ย {fmt_num(f.avg_total)} | 5 นัดหลัง {fmt_num(f.last5_total)}")
    out.append("-" * 72)

    out.append("ผลคาดการณ์")
    out.append(f"   {m.home.name}: {a.home_exp:.2f}   {m.away.name}: {a.away_exp:.2f}")
    sd_s = f"  (±{a.sd:.1f} ส่วนเบี่ยงเบนมาตรฐาน)" if a.sd else ""
    out.append(f"   สกอร์รวมคาดการณ์: {a.total:.2f} {u}{sd_s}")
    if "market_total" in a.extras:
        w = a.extras["model_weight"]
        out.append(f"   (โมเดลล้วน {a.extras['raw_total']:.2f} · ตลาดคาด {a.extras['market_total']:.2f}"
                   f" · ผสม {w:.0%}/{1 - w:.0%})")
    if lg.model == NORMAL and a.sd:
        lo, hi = a.total - 1.28 * a.sd, a.total + 1.28 * a.sd
        out.append(f"   ช่วง 80%: {lo:.0f} – {hi:.0f} {u}")

    ex = a.extras
    if lg.sport == SOCCER and ex:
        out.append(f"   ชนะ/เสมอ/แพ้ (เจ้าบ้าน): {ex['p_home_win']:.0%} / {ex['p_draw']:.0%} / "
                   f"{ex['p_away_win']:.0%}   ยิงได้ทั้งสองทีม (BTTS): {ex['p_btts']:.0%}")
    elif ex.get("p_home_win") is not None:
        out.append(f"   โอกาสชนะ: {m.home.name} {ex['p_home_win']:.0%} / "
                   f"{m.away.name} {ex['p_away_win']:.0%}")
    if ex.get("top_scores"):
        ts = ", ".join(f"{s['score']} ({s['p']:.0%})" for s in ex["top_scores"][:4])
        out.append(f"   สกอร์ที่น่าจะเป็น (เหย้า-เยือน): {ts}")
    if a.dist and lg.sport == SOCCER:
        bins = "  ".join(f"{k}:{a.dist[k]:.0%}" for k in range(7))
        out.append(f"   จำนวน{u}รวม: {bins}  7+:{sum(a.dist[7:]):.0%}")
    out.append("-" * 72)

    out.append("เทียบไลน์สกอร์รวม")
    if a.main is not None:
        mn = a.main
        out.append(f"   ไลน์หลัก: {mn.line:g} ({a.line_source})  ราคา สูง {fmt_odds(mn.over_odds)}"
                   f" / ต่ำ {fmt_odds(mn.under_odds)}")
    else:
        out.append("   ไม่มีไลน์จากเจ้ามือ — ใช้ --line เพื่อกำหนดเอง (แสดงไลน์อ้างอิงด้านล่าง)")
    for x in a.ladder:
        out.append(_line_row(x, u) + ("  ◀ หลัก" if a.main is x else ""))
    out.append("-" * 72)

    if a.pick:
        p = a.main.p_over if a.pick == "over" else a.main.p_under
        ev = a.main.ev_over if a.pick == "over" else a.main.ev_under
        out.append(f"สรุป: {a.strength} {PICK_TH[a.pick]} {a.main.line:g}  "
                   f"(โอกาส {p:.1%}, ผลตอบแทนคาดหวัง {ev:+.1%} ต่อหน่วย)")
    elif a.main is not None:
        out.append("สรุป: ผ่าน — ไม่พบความได้เปรียบเพียงพอเทียบกับไลน์")
    else:
        out.append(f"สรุป: ไม่มีไลน์อ้างอิง — โมเดลคาดสกอร์รวม {a.total:.1f} {u} "
                   "(กำหนดไลน์ด้วย --line เพื่อดูคำแนะนำ)")
    if a.winner is not None:
        out.append("-" * 72)
        out.extend(render_winner(a.winner, {"home": m.home.name, "away": m.away.name, "draw": "เสมอ"}))
    out.append(f"ความน่าเชื่อถือของข้อมูล: {a.data_quality}")
    for n in a.notes:
        out.append(f" ⚠ {n}")
    return "\n".join(out)


def render_winner(w, names: dict) -> list[str]:
    order = [k for k in ("home", "draw", "away") if k in w.model]
    fmtp = lambda d: " / ".join(f"{names[k]} {d[k]:.1%}" for k in order)
    out = ["ผู้ชนะ", f"   โมเดล: {fmtp(w.model)}"]
    if w.market is not None:
        odds = " / ".join(f"{names[k]} {fmt_odds(w.odds[k])}" for k in order)
        out.append(f"   ราคา ({w.source}): {odds}  → ตลาด (ตัดค่าน้ำ) {fmtp(w.market)}")
        out.append(f"   ใช้ตัดสิน (ผสมกับตลาด): {fmtp(w.prob)}")
        out.append("   edge: " + " / ".join(f"{names[k]} {w.edges[k]:+.1%}" for k in order))
        if w.pick:
            out.append(f"สรุปผู้ชนะ: {w.strength} {names[w.pick]} (ราคา {fmt_odds(w.odds[w.pick])},"
                       f" โอกาส {w.prob[w.pick]:.1%})")
        else:
            out.append("สรุปผู้ชนะ: ผ่าน — ราคาสอดคล้องกับโอกาสแล้ว")
    else:
        fav = w.favorite
        out.append(f"สรุปผู้ชนะ: โมเดลให้ {names[fav]} มีโอกาสมากกว่า ({w.prob[fav]:.1%}) — "
                   "ไม่มีราคาเจ้ามือ ใส่ --ml-home/--ml-away เพื่อเทียบราคา")
    return out


def render_summary(analyses: list[Analysis]) -> str:
    if not analyses:
        return ""
    rows = ["", "สรุปทุกคู่", "-" * 72]
    for a in analyses:
        m = a.match
        line = f"{a.main.line:g}" if a.main else "-"
        pick = f"{a.strength} {PICK_TH[a.pick]}" if a.pick else (a.strength if a.main else "ไม่มีไลน์")
        wn = ""
        if a.winner is not None:
            names = {"home": m.home.abbr or m.home.name, "away": m.away.abbr or m.away.name, "draw": "เสมอ"}
            f = a.winner.favorite
            wn = f" | ชนะ: {names[f]} {a.winner.prob[f]:.0%}"
            if a.winner.pick:
                wn += f" ({a.winner.strength} {names[a.winner.pick]})"
        rows.append(f"{m.away.abbr or m.away.name} @ {m.home.abbr or m.home.name}: "
                    f"คาด {a.total:.1f} | ไลน์ {line} | {pick}{wn} | ข้อมูล{a.data_quality}")
    return "\n".join(rows)


DISCLAIMER = ("หมายเหตุ: ผลวิเคราะห์เป็นการประมาณทางสถิติจากผลงานย้อนหลังเท่านั้น "
              "ไม่รวมข่าวผู้เล่นบาดเจ็บ/ตัวจริง สภาพอากาศ หรือแรงจูงใจ และไม่รับประกันผล")
