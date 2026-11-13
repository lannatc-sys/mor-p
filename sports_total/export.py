"""ส่งออกผลวิเคราะห์นัดที่ยังไม่เริ่ม เป็นไฟล์ JSON หนึ่งไฟล์ต่อลีก สำหรับหน้าเว็บ

แต่ละไฟล์คือเอกสารหนึ่งชิ้นในคอลเลกชัน `slates` ของฐานข้อมูลหน้าเว็บ
หน้าเว็บคำนวณความน่าจะเป็นของไลน์อื่นเองได้จาก proj/sd หรือ dist
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .analyzer import Analysis, LineEval, TotalAnalyzer
from .espn import FetchError
from .leagues import get_league

US_EAST = timezone(timedelta(hours=-5))

# ลีกที่ส่งออกโดยค่าเริ่มต้น และจำนวนวันที่ดูล่วงหน้า
DEFAULT_PLAN = {
    "nba": 2, "nfl": 7, "ncaaf": 7, "mlb": 2,
    "epl": 10, "laliga": 10, "seriea": 10, "bundesliga": 10, "ligue1": 10,
    "ucl": 14, "uel": 14, "thaileague": 10, "jleague": 10,
}


def _r(x, nd=3):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(x, nd)


def _trim_dist(dist):
    if not dist:
        return None
    out, cum = [], 0.0
    for p in dist:
        out.append(_r(p, 5))
        cum += p
        if cum > 0.99999 and len(out) >= 8:
            break
    return out


def _line(x: LineEval | None):
    if x is None:
        return None
    return {"line": x.line, "over": _r(x.p_over, 4), "under": _r(x.p_under, 4),
            "push": _r(x.p_push, 4), "over_odds": x.over_odds, "under_odds": x.under_odds,
            "edge_over": _r(x.edge_over, 4), "edge_under": _r(x.edge_under, 4)}


def match_doc(a: Analysis) -> dict:
    m = a.match

    def team(t, f):
        return {"name": t.name, "abbr": t.abbr, "record": t.record, "n": f.n,
                "for": _r(f.w_for, 2), "against": _r(f.w_against, 2),
                "avg_total": _r(f.avg_total, 2), "last5": _r(f.last5_total, 2)}

    mk = m.market
    return {
        "id": m.event_id, "start": m.start.astimezone(timezone.utc).isoformat(),
        "status": m.status_detail, "venue": m.venue,
        "home": team(m.home, a.home_form), "away": team(m.away, a.away_form),
        "proj": {"home": _r(a.home_exp, 2), "away": _r(a.away_exp, 2),
                 "total": _r(a.total, 2), "sd": _r(a.sd, 2)},
        "dist": _trim_dist(a.dist),
        "market": ({"provider": mk.provider, "line": mk.line, "over_odds": mk.over_odds,
                    "under_odds": mk.under_odds, "details": mk.details} if mk else None),
        "main": _line(a.main), "line_source": a.line_source,
        "pick": a.pick, "strength": a.strength, "quality": a.data_quality,
        "notes": a.notes, "extras": a.extras,
    }


def export_league(client, key: str, days: int, last_n: int = 10, log=None) -> dict:
    lg = get_league(key)
    today = datetime.now(US_EAST).date()
    matches = [m for m in client.scoreboard(lg, today, days) if m.is_pregame]
    an = TotalAnalyzer(lg, client, last_n=last_n)
    docs = []
    for m in matches:
        try:
            docs.append(match_doc(an.analyze(m)))
        except FetchError as e:
            if log:
                log(f"  ข้าม {m.away.name} @ {m.home.name}: {e}")
    return {
        "league": lg.key, "name": lg.name_th, "sport": lg.sport, "sport_th": lg.sport_th,
        "unit": lg.unit_th, "model": lg.model,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "days": days, "matches": docs,
    }


def run_export(client, out_dir: str, plan: dict[str, int], last_n: int = 10) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    def log(s):
        print(s, file=sys.stderr)

    written = []
    for key, days in plan.items():
        try:
            doc = export_league(client, key, days, last_n, log)
        except FetchError as e:
            log(f"{key}: ดึงข้อมูลไม่สำเร็จ ({e})")
            continue
        path = out / f"{key}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        log(f"{key}: {len(doc['matches'])} นัด -> {path} ({path.stat().st_size // 1024} KB)")
        written.append(path)
    return written
