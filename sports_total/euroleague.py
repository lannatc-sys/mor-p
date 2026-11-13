"""แหล่งข้อมูลยูโรลีก/ยูโรคัพ จาก API ทางการ (api-live.euroleague.net) — ไม่ต้องใช้ key

ESPN มีรายชื่อทีมยูโรลีกแต่ไม่มีข้อมูลนัด จึงใช้ API นี้แทน
- ตารางและผลทั้งฤดูกาล: /v2/competitions/{E|U}/seasons/{E|U}{ปี}/games
- ไม่มีราคาเจ้ามือ ผู้ใช้ต้องกำหนดไลน์เอง
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .espn import FetchError, parse_dt
from .leagues import League
from .models import GameResult, Match, Team

API = "https://api-live.euroleague.net/v2/competitions"
US_EAST = timezone(timedelta(hours=-5))


def season_year(today: date) -> int:
    """ฤดูกาลยุโรปเริ่มราวกรกฎาคม: พ.ย. 2026 -> ฤดูกาล 2026 (2026-27)"""
    return today.year if today.month >= 7 else today.year - 1


def _start(g: dict) -> datetime | None:
    return parse_dt(g.get("utcDate")) or parse_dt(g.get("date"))


def _team(side: dict) -> Team:
    club = side.get("club") or {}
    return Team(
        id=str(club.get("code") or ""),
        name=club.get("name") or club.get("abbreviatedName") or "?",
        abbr=club.get("tvCode") or club.get("code") or "",
    )


def parse_games(data: dict) -> list[dict]:
    return [g for g in (data.get("data") or []) if isinstance(g, dict) and g.get("local") and g.get("road")]


def records(games: list[dict]) -> dict[str, str]:
    """สถิติชนะ-แพ้ของแต่ละทีมในฤดูกาล จากเกมที่จบแล้ว"""
    wl: dict[str, list[int]] = {}
    for g in games:
        if not g.get("played"):
            continue
        h, a = _team(g["local"]).id, _team(g["road"]).id
        hs, as_ = g["local"].get("score") or 0, g["road"].get("score") or 0
        for tid in (h, a):
            wl.setdefault(tid, [0, 0])
        wl[h][0 if hs > as_ else 1] += 1
        wl[a][0 if as_ > hs else 1] += 1
    return {k: f"{w}-{l}" for k, (w, l) in wl.items()}


class EuroLeagueSource:
    def __init__(self, http):
        self.http = http   # ESPNClient (ใช้ fetch_url และแคชร่วมกัน)

    def season_games(self, league: League, year: int, ttl: int = 1800) -> list[dict]:
        code = league.slug
        return parse_games(self.http.fetch_url(f"{API}/{code}/seasons/{code}{year}/games", ttl))

    def scoreboard(self, league: League, day: date | None = None, days: int = 1) -> list[Match]:
        today = datetime.now(US_EAST).date()
        day = day or today
        end = day + timedelta(days=max(days, 1) - 1)
        games = self.season_games(league, season_year(day), ttl=300)
        recs = records(games)
        now = datetime.now(timezone.utc)
        out = []
        for g in games:
            start = _start(g)
            if start is None or not (day <= start.astimezone(US_EAST).date() <= end):
                continue
            home, away = _team(g["local"]), _team(g["road"])
            home.record, away.record = recs.get(home.id, ""), recs.get(away.id, "")
            played = bool(g.get("played"))
            state = "post" if played else ("in" if start <= now else "pre")
            out.append(Match(
                event_id=str(g.get("identifier") or g.get("gameCode")),
                league_key=league.key, start=start, state=state,
                status_detail="จบแล้ว" if played else (g.get("roundAlias") or g.get("roundName") or ""),
                home=home, away=away,
                venue=(g.get("venue") or {}).get("name") or "",
                home_score=float(g["local"].get("score") or 0) if played else None,
                away_score=float(g["road"].get("score") or 0) if played else None,
            ))
        return sorted(out, key=lambda m: m.start)

    def team_games(self, league: League, team_id: str, before: datetime | None = None,
                   want: int = 10) -> list[GameResult]:
        ref = (before or datetime.now(timezone.utc)).astimezone(US_EAST).date()
        year = season_year(ref)
        results: list[GameResult] = []
        for y, ttl in ((year, 1800), (year - 1, 86400)):
            if y != year and len(results) >= want:
                break
            try:
                games = self.season_games(league, y, ttl)
            except FetchError:
                continue
            for g in games:
                if not g.get("played"):
                    continue
                start = _start(g)
                if start is None or (before is not None and start >= before):
                    continue
                for me, opp, home in (("local", "road", True), ("road", "local", False)):
                    if _team(g[me]).id == team_id:
                        results.append(GameResult(
                            event_id=str(g.get("identifier")), date=start, team_id=team_id,
                            opponent=_team(g[opp]).name, is_home=home,
                            points_for=float(g[me].get("score") or 0),
                            points_against=float(g[opp].get("score") or 0)))
        results.sort(key=lambda r: r.date, reverse=True)
        return results
