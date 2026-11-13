"""คำสั่งใช้งาน

    python -m sports_total leagues
    python -m sports_total games nba --date 2026-11-14
    python -m sports_total analyze nba --date 2026-11-14
    python -m sports_total analyze epl --days 3 --team arsenal
    python -m sports_total analyze nfl --event 401772900 --line 47.5
    python -m sports_total manual nba --home-for 118 --home-against 110 --away-for 112 --away-against 115 --line 228.5
    python -m sports_total demo nba
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

from . import __version__
from .analyzer import TotalAnalyzer, TeamForm
from .espn import ESPNClient, FetchError
from .leagues import LEAGUES, SPORT_NAMES_TH, League, get_league
from .models import Match, Team
from .report import DISCLAIMER, match_line, render, render_summary

try:
    from zoneinfo import ZoneInfo
    US_TZ = ZoneInfo("America/New_York")
except Exception:
    US_TZ = timezone(timedelta(hours=-5))


def parse_date(s: str | None) -> date | None:
    """วันที่ตามปฏิทินสหรัฐฯ (ESPN ใช้เวลาฝั่งตะวันออกสหรัฐฯ)"""
    if not s:
        return None
    today = datetime.now(US_TZ).date()
    s = s.strip().lower()
    if s in ("today", "วันนี้"):
        return today
    if s in ("tomorrow", "พรุ่งนี้"):
        return today + timedelta(days=1)
    if s in ("yesterday", "เมื่อวาน"):
        return today - timedelta(days=1)
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(f"รูปแบบวันที่ไม่ถูกต้อง: {s} (ใช้ YYYY-MM-DD)")


def _team_match(m: Match, q: str) -> bool:
    q = q.lower()
    return any(q in (x or "").lower() for x in (m.home.name, m.away.name, m.home.abbr, m.away.abbr))


# ------------------------------------------------------------- commands ---

def cmd_leagues(args) -> int:
    by_sport: dict[str, list[League]] = {}
    for lg in LEAGUES.values():
        by_sport.setdefault(lg.sport, []).append(lg)
    for sport, lgs in by_sport.items():
        print(f"\n{SPORT_NAMES_TH[sport]}")
        for lg in lgs:
            print(f"  {lg.key:<13} {lg.name_th}  (ESPN: {lg.sport}/{lg.slug})")
    print("\nลีกฟุตบอลอื่นของ ESPN: ใช้ soccer:<รหัส> เช่น soccer:por.1, soccer:sco.1")
    return 0


def _fetch_matches(args, client) -> tuple[League, list[Match]]:
    league = get_league(args.league)
    matches = client.scoreboard(league, parse_date(args.date), args.days)
    if args.team:
        matches = [m for m in matches if _team_match(m, args.team)]
    if getattr(args, "event", None):
        matches = [m for m in matches if m.event_id == str(args.event)]
    return league, matches


def cmd_games(args, client) -> int:
    league, matches = _fetch_matches(args, client)
    if not matches:
        print(f"ไม่พบนัดแข่งของ {league.name_th} ในช่วงวันที่ที่เลือก")
        return 1
    print(f"{league.sport_th} | {league.name_th} — {len(matches)} นัด")
    for m in matches:
        print(" " + match_line(m))
    return 0


def _run_analysis(args, client, league: League, matches: list[Match]) -> int:
    if not args.include_started:
        skipped = [m for m in matches if not m.is_pregame]
        matches = [m for m in matches if m.is_pregame]
        if skipped and not args.json:
            print(f"(ข้าม {len(skipped)} นัดที่เริ่มแล้ว/จบแล้ว — ใช้ --include-started เพื่อรวม)")
    if not matches:
        print("ไม่พบนัดที่ยังไม่เริ่มให้วิเคราะห์")
        return 1

    analyzer = TotalAnalyzer(league, client, last_n=args.last, half_life=args.half_life,
                             league_avg=args.league_avg, model_weight=args.model_weight)
    results = []
    for m in matches:
        try:
            results.append(analyzer.analyze(m, line=args.line, over_odds=args.over_odds,
                                            under_odds=args.under_odds))
        except FetchError as e:
            print(f"ข้าม {m.away.name} @ {m.home.name}: {e}", file=sys.stderr)

    if args.json:
        print(json.dumps([a.to_dict() for a in results], ensure_ascii=False, indent=2))
        return 0
    for a in results:
        print(render(a))
    if len(results) > 1:
        print(render_summary(results))
    print("\n" + DISCLAIMER)
    return 0


def cmd_analyze(args, client) -> int:
    league, matches = _fetch_matches(args, client)
    return _run_analysis(args, client, league, matches)


def cmd_export(args, client) -> int:
    from .export import DEFAULT_PLAN, run_export
    plan = DEFAULT_PLAN
    if args.leagues:
        plan = {}
        for part in args.leagues.split(","):
            key, _, days = part.strip().partition(":")
            get_league(key)
            plan[key] = int(days or 3)
    return 0 if run_export(client, args.out_dir, plan, args.last) else 3


def cmd_demo(args) -> int:
    from .demo import DemoClient
    league = get_league(args.league)
    client = DemoClient(league)
    print(f"*** โหมดสาธิต: ข้อมูลจำลอง ไม่ใช่ข้อมูลจริง ({league.name_th}) ***\n")
    return _run_analysis(args, client, league, client.scoreboard(league))


def cmd_manual(args) -> int:
    league = get_league(args.league)
    home = Team("home", args.home)
    away = Team("away", args.away)
    match = Match("manual", league.key, datetime.now(timezone.utc), "pre", "กำหนดเอง", home, away)
    hf = TeamForm.manual(home, args.home_for, args.home_against, args.games)
    af = TeamForm.manual(away, args.away_for, args.away_against, args.games)
    a = TotalAnalyzer(league, league_avg=args.league_avg).evaluate(
        match, hf, af, line=args.line, over_odds=args.over_odds, under_odds=args.under_odds)
    if args.json:
        print(json.dumps(a.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render(a))
        print("\n" + DISCLAIMER)
    return 0


# ---------------------------------------------------------------- parser ---

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sports_total",
        description="โปรแกรมวิเคราะห์สกอร์รวม (Over/Under) บาสเกตบอล ฟุตบอล เบสบอล อเมริกันฟุตบอล")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--no-cache", action="store_true", help="ไม่ใช้แคชข้อมูล")
    p.add_argument("--timeout", type=float, default=15.0, help="เวลารอการเชื่อมต่อ (วินาที)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("leagues", help="แสดงลีกที่รองรับ")

    def add_fetch(sp):
        sp.add_argument("league", help="ชื่อย่อลีก เช่น nba, epl, mlb, nfl")
        sp.add_argument("--date", help="วันที่แข่ง (ปฏิทินสหรัฐฯ) YYYY-MM-DD / today / tomorrow")
        sp.add_argument("--days", type=int, default=1, help="จำนวนวันนับจาก --date")
        sp.add_argument("--team", help="กรองเฉพาะทีม (ชื่อหรือตัวย่อ)")

    def add_model(sp, line_help="ไลน์สกอร์รวมที่ต้องการเทียบ (แทนไลน์เจ้ามือ)"):
        sp.add_argument("--line", type=float, help=line_help)
        sp.add_argument("--over-odds", type=float, help="ราคาฝั่งสูงแบบอเมริกัน เช่น -110")
        sp.add_argument("--under-odds", type=float, help="ราคาฝั่งต่ำแบบอเมริกัน เช่น -110")
        sp.add_argument("--league-avg", type=float, help="คะแนนเฉลี่ยต่อทีมต่อเกมของลีก (แทนค่าตั้งต้น)")
        sp.add_argument("--model-weight", type=float, default=0.4,
                        help="น้ำหนักของโมเดลเมื่อมีไลน์เจ้ามือ 0-1 (ค่าเริ่มต้น 0.4, 1 = ใช้โมเดลล้วน)")
        sp.add_argument("--json", action="store_true", help="แสดงผลเป็น JSON")

    def add_form(sp):
        sp.add_argument("--last", type=int, default=10, help="จำนวนนัดล่าสุดที่ใช้ (ค่าเริ่มต้น 10)")
        sp.add_argument("--half-life", type=float, default=6.0,
                        help="ครึ่งชีวิตของน้ำหนัก (นัด) — น้อย = เน้นฟอร์มล่าสุดมาก")
        sp.add_argument("--include-started", action="store_true", help="รวมนัดที่เริ่ม/จบแล้ว")

    g = sub.add_parser("games", help="แสดงรายการนัดแข่ง")
    add_fetch(g)

    an = sub.add_parser("analyze", help="ดึงนัดก่อนเริ่มเกมแล้ววิเคราะห์สกอร์รวม")
    add_fetch(an)
    an.add_argument("--event", help="วิเคราะห์เฉพาะรหัสนัด (ดูจากคำสั่ง games)")
    add_model(an)
    add_form(an)

    d = sub.add_parser("demo", help="ทดลองด้วยข้อมูลจำลอง (ไม่ต้องใช้อินเทอร์เน็ต)")
    d.add_argument("league", choices=["nba", "epl", "mlb", "nfl"])
    add_model(d)
    add_form(d)

    ex = sub.add_parser("export", help="ส่งออกผลวิเคราะห์ (JSON ต่อลีก) สำหรับหน้าเว็บ")
    ex.add_argument("--out-dir", default="web_data", help="โฟลเดอร์ปลายทาง")
    ex.add_argument("--leagues", help="ลีกที่ต้องการ เช่น nba:2,epl:7 (ลีก:จำนวนวัน)")
    ex.add_argument("--last", type=int, default=10)

    mn = sub.add_parser("manual", help="วิเคราะห์จากค่าเฉลี่ยที่กรอกเอง (ไม่ต้องใช้อินเทอร์เน็ต)")
    mn.add_argument("league")
    mn.add_argument("--home", default="ทีมเหย้า")
    mn.add_argument("--away", default="ทีมเยือน")
    for side in ("home", "away"):
        mn.add_argument(f"--{side}-for", type=float, required=True, help="คะแนนได้เฉลี่ยต่อเกม")
        mn.add_argument(f"--{side}-against", type=float, required=True, help="คะแนนเสียเฉลี่ยต่อเกม")
    mn.add_argument("--games", type=int, default=10, help="จำนวนเกมที่ใช้คิดค่าเฉลี่ย")
    add_model(mn)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except BrokenPipeError:  # เช่น ส่งผลต่อให้ head แล้วถูกตัด
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return 0


def _dispatch(args) -> int:
    try:
        if args.cmd == "leagues":
            return cmd_leagues(args)
        if args.cmd == "demo":
            return cmd_demo(args)
        if args.cmd == "manual":
            return cmd_manual(args)
        client = ESPNClient(timeout=args.timeout, use_cache=not args.no_cache)
        if args.cmd == "games":
            return cmd_games(args, client)
        if args.cmd == "export":
            return cmd_export(args, client)
        return cmd_analyze(args, client)
    except (KeyError, argparse.ArgumentTypeError) as e:
        print(f"ผิดพลาด: {e.args[0] if e.args else e}", file=sys.stderr)
        return 2
    except FetchError as e:
        print(f"ผิดพลาด: {e}\nตรวจสอบการเชื่อมต่ออินเทอร์เน็ต หรือว่าเครือข่ายอนุญาตให้เข้าถึง "
              "site.api.espn.com", file=sys.stderr)
        return 3
