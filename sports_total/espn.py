"""ตัวดึงข้อมูลจาก ESPN public API (ไม่ต้องใช้ API key)

- scoreboard  : รายการนัดแข่ง (รวมนัดที่ยังไม่เริ่ม) พร้อมราคาสกอร์รวมถ้ามี
- team_games  : ผลการแข่งขันที่จบแล้วของทีม ใช้คำนวณฟอร์มก่อนเกม

หมายเหตุ: API นี้ไม่ใช่ API ทางการที่มีเอกสารรับรอง โครงสร้างข้อมูลอาจเปลี่ยนได้
ตัวแปลงข้อมูลจึงเขียนแบบยืดหยุ่นและข้ามรายการที่อ่านไม่ได้
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .leagues import League
from .models import GameResult, MarketTotal, Match, Team

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"


class FetchError(RuntimeError):
    pass


# ---------------------------------------------------------------- helpers ---

def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%dT%H:%M%z"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_score(v) -> float | None:
    """คะแนนใน scoreboard เป็นสตริง แต่ใน schedule เป็น {"value":..,"displayValue":..}"""
    if v is None:
        return None
    if isinstance(v, dict):
        v = v.get("value", v.get("displayValue"))
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_american(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().upper()
    if s in ("EVEN", "EV"):
        return 100.0
    try:
        return float(s.replace("+", ""))
    except ValueError:
        return None


def parse_line(v) -> float | None:
    """รองรับ 224.5 / "224.5" / "o224.5" / "u224.5" """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower().lstrip("ou")
    try:
        return float(s)
    except ValueError:
        return None


def _status(obj: dict) -> tuple[str, str, bool]:
    st = (obj or {}).get("status") or {}
    t = st.get("type") or {}
    state = t.get("state") or ""
    completed = bool(t.get("completed")) or state == "post"
    detail = t.get("shortDetail") or t.get("detail") or t.get("description") or ""
    return state, detail, completed


def _team(comp: dict) -> Team:
    t = comp.get("team") or {}
    record = ""
    for r in comp.get("records") or comp.get("record") or []:
        if isinstance(r, dict) and r.get("summary"):
            if r.get("type") in (None, "total") or r.get("name") == "overall":
                record = r["summary"]
                break
    return Team(
        id=str(t.get("id") or comp.get("id") or ""),
        name=t.get("displayName") or t.get("name") or t.get("shortDisplayName") or "?",
        abbr=t.get("abbreviation") or "",
        record=record,
    )


def _markets(comp: dict) -> list[MarketTotal]:
    out = []
    for o in comp.get("odds") or []:
        line = parse_line(o.get("overUnder"))
        over_odds = parse_american(o.get("overOdds"))
        under_odds = parse_american(o.get("underOdds"))
        tot = o.get("total") or {}
        if tot:  # รูปแบบใหม่: total.over.close.{line,odds}
            for side, attr in (("over", "over_odds"), ("under", "under_odds")):
                s = tot.get(side) or {}
                for phase in ("close", "current", "open"):
                    p = s.get(phase) or {}
                    if line is None:
                        line = parse_line(p.get("line"))
                    val = parse_american(p.get("odds") or p.get("american"))
                    if val is not None:
                        if attr == "over_odds" and over_odds is None:
                            over_odds = val
                        if attr == "under_odds" and under_odds is None:
                            under_odds = val
                        break
        if line is None:
            continue
        out.append(MarketTotal(
            provider=(o.get("provider") or {}).get("name") or "ไม่ระบุ",
            line=line, over_odds=over_odds, under_odds=under_odds,
            details=o.get("details") or "",
        ))
    return out


def parse_scoreboard(data: dict, league_key: str) -> list[Match]:
    matches = []
    for ev in data.get("events") or []:
        try:
            comp = (ev.get("competitions") or [{}])[0]
            comps = comp.get("competitors") or []
            home = next((c for c in comps if c.get("homeAway") == "home"), None)
            away = next((c for c in comps if c.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            state, detail, _ = _status(ev if ev.get("status") else comp)
            start = parse_dt(ev.get("date") or comp.get("date"))
            if start is None:
                continue
            matches.append(Match(
                event_id=str(ev.get("id")),
                league_key=league_key,
                start=start,
                state=state,
                status_detail=detail,
                home=_team(home),
                away=_team(away),
                venue=((comp.get("venue") or {}).get("fullName") or ""),
                markets=_markets(comp),
                home_score=parse_score(home.get("score")),
                away_score=parse_score(away.get("score")),
            ))
        except Exception:  # ข้ามรายการที่รูปแบบผิด
            continue
    matches.sort(key=lambda m: m.start)
    return matches


def parse_team_schedule(data: dict, team_id: str) -> list[GameResult]:
    results = []
    for ev in data.get("events") or []:
        try:
            comp = (ev.get("competitions") or [{}])[0]
            _, _, completed = _status(comp if comp.get("status") else ev)
            if not completed:
                continue
            comps = comp.get("competitors") or []
            me = next((c for c in comps if _team(c).id == str(team_id)), None)
            opp = next((c for c in comps if c is not me), None)
            if me is None or opp is None:
                continue
            pf, pa = parse_score(me.get("score")), parse_score(opp.get("score"))
            dt = parse_dt(ev.get("date") or comp.get("date"))
            if pf is None or pa is None or dt is None:
                continue
            results.append(GameResult(
                event_id=str(ev.get("id")), date=dt, team_id=str(team_id),
                opponent=_team(opp).name, is_home=me.get("homeAway") == "home",
                points_for=pf, points_against=pa,
            ))
        except Exception:
            continue
    return results


def season_year(data: dict) -> int | None:
    for k in ("requestedSeason", "season"):
        y = (data.get(k) or {}).get("year")
        if isinstance(y, int):
            return y
    return None


# ----------------------------------------------------------------- client ---

class ESPNClient:
    def __init__(self, timeout: float = 15.0, use_cache: bool = True,
                 cache_dir: str | os.PathLike | None = None, retries: int = 2):
        self.timeout = timeout
        self.retries = retries
        self.use_cache = use_cache
        self.cache_dir = Path(cache_dir or Path.home() / ".cache" / "sports_total")
        self._mem: dict[str, dict] = {}

    # -- low level --
    def get_json(self, path: str, params: dict | None = None, ttl: int = 600) -> dict:
        qs = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = f"{BASE_URL}/{path}" + (f"?{qs}" if qs else "")
        if url in self._mem:
            return self._mem[url]
        cache_file = self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".json")
        if self.use_cache and cache_file.exists() and time.time() - cache_file.stat().st_mtime < ttl:
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                self._mem[url] = data
                return data
            except (OSError, ValueError):
                pass

        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (sports-total-analyzer)",
            "Accept": "application/json",
        })
        data: dict | None = None
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code in (400, 403, 404):
                    break
            except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
                last_err = e
            if attempt < self.retries:
                time.sleep(1.0 * (attempt + 1))
        if data is None:
            raise FetchError(f"ดึงข้อมูลไม่สำเร็จ: {url} ({last_err})")

        self._mem[url] = data
        if self.use_cache:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(data), encoding="utf-8")
            except OSError:
                pass
        return data

    # -- high level --
    def scoreboard(self, league: League, day: date | None = None, days: int = 1) -> list[Match]:
        params = dict(league.scoreboard_params)
        if day is not None:
            end = day + timedelta(days=max(days, 1) - 1)
            params["dates"] = day.strftime("%Y%m%d") + (
                "-" + end.strftime("%Y%m%d") if end != day else "")
        data = self.get_json(f"{league.sport}/{league.slug}/scoreboard", params, ttl=300)
        return parse_scoreboard(data, league.key)

    def team_games(self, league: League, team_id: str, before: datetime | None = None,
                   want: int = 10) -> list[GameResult]:
        """ผลการแข่งขันล่าสุดของทีม (ใหม่ -> เก่า) เฉพาะเกมที่จบก่อน `before`
        ถ้าฤดูกาลนี้มีไม่พอ จะดึงฤดูกาลก่อนหน้ามาเติม"""
        path = f"{league.sport}/{league.slug}/teams/{team_id}/schedule"
        data = self.get_json(path, ttl=3600)
        games = parse_team_schedule(data, team_id)
        games = [g for g in games if before is None or g.date < before]
        year = season_year(data)
        if len(games) < want and year:
            try:
                prev = self.get_json(path, {"season": year - 1}, ttl=86400)
                seen = {g.event_id for g in games}
                games += [g for g in parse_team_schedule(prev, team_id)
                          if g.event_id not in seen and (before is None or g.date < before)]
            except FetchError:
                pass
        games.sort(key=lambda g: g.date, reverse=True)
        return games
